# servo_control.py
# -*- coding: utf-8 -*-
"""
ESP32舵机控制Web服务
支持：单舵机控制、镜像控制、多选控制、动作编排、动作序列播放
"""
import asyncio
import json
from typing import Dict, List, Optional
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import httpx
import os

# ===== ESP32配置 =====
# 重要：修改为你的ESP32实际IP地址！
# 在ESP32串口监视器中可以看到连接WiFi后的IP
ESP32_IP = "192.168.2.10"  # 修改为你的ESP32 IP（从串口看）
ESP32_PORT = 80
ESP32_SERVO_URL = f"http://{ESP32_IP}:{ESP32_PORT}/servo"

print(f"[CONFIG] ESP32地址: {ESP32_SERVO_URL}")

app = FastAPI()

# ===== 动作序列存储 =====
action_sequences: Dict[str, List[Dict]] = {}

# ===== WebSocket连接管理 =====
connected_clients: List[WebSocket] = []

# ===== 舵机控制API =====
async def set_servo(ch: int, angle: int) -> Dict:
    """向ESP32发送舵机控制命令（GET请求，与test.py一致）"""
    angle = max(0, min(180, int(angle)))
    url = f"{ESP32_SERVO_URL}?ch={ch}&angle={angle}"
    
    print(f"[REQ] 发送到ESP32: ch={ch}, angle={angle}, URL={url}")
    
    async with httpx.AsyncClient(timeout=2.0) as client:  # 增加超时时间
        try:
            response = await client.get(
                ESP32_SERVO_URL,
                params={"ch": ch, "angle": angle}
            )
            result = {
                "success": True,
                "ch": ch,
                "angle": angle,
                "response": response.text
            }
            print(f"[RESP] ESP32响应: {response.text}")
            return result
        except httpx.ConnectError as e:
            error_msg = f"无法连接到ESP32 ({ESP32_IP}): {e}"
            print(f"[ERROR] {error_msg}")
            return {
                "success": False,
                "ch": ch,
                "angle": angle,
                "error": error_msg
            }
        except httpx.TimeoutException as e:
            error_msg = f"ESP32响应超时: {e}"
            print(f"[ERROR] {error_msg}")
            return {
                "success": False,
                "ch": ch,
                "angle": angle,
                "error": error_msg
            }
        except Exception as e:
            error_msg = f"请求失败: {e}"
            print(f"[ERROR] {error_msg}")
            return {
                "success": False,
                "ch": ch,
                "angle": angle,
                "error": error_msg
            }

@app.post("/api/servo/set")
@app.get("/api/servo/set")  # 同时支持GET和POST
async def api_set_servo(ch: int, angle: int):
    """设置单个舵机"""
    result = await set_servo(ch, angle)
    return result

@app.post("/api/servo/set_multiple")
async def api_set_multiple(channels: List[int], angle: int):
    """设置多个舵机到同一角度"""
    results = []
    for ch in channels:
        result = await set_servo(ch, angle)
        results.append(result)
    return {"results": results}

@app.post("/api/servo/mirror")
@app.get("/api/servo/mirror")  # 同时支持GET和POST
async def api_mirror_servo(ch_a: int, ch_b: int, angle: int):
    """镜像控制：ch_a=angle, ch_b=180-angle"""
    angle_b = 180 - angle
    result_a = await set_servo(ch_a, angle)
    result_b = await set_servo(ch_b, angle_b)
    return {
        "a": result_a,
        "b": result_b
    }

# ===== 测试接口：直接转发到ESP32 =====
@app.get("/test_servo")
async def test_servo_direct(ch: int, angle: int):
    """测试接口：直接检查能否连接ESP32"""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                ESP32_SERVO_URL,
                params={"ch": ch, "angle": angle}
            )
            return {
                "success": True,
                "esp32_ip": ESP32_IP,
                "ch": ch,
                "angle": angle,
                "esp32_response": response.text,
                "status_code": response.status_code
            }
    except Exception as e:
        return {
            "success": False,
            "esp32_ip": ESP32_IP,
            "error": str(e),
            "help": "请检查: 1) ESP32是否已上电并连接WiFi 2) IP地址是否正确 3) 防火墙设置"
        }

# ===== 动作序列API =====
@app.post("/api/action/save")
async def api_save_action(name: str, actions: List[Dict]):
    """
    保存动作序列
    actions格式: [
        {
            "servos": {"0": 90, "1": 45, ...},  # 舵机编号: 角度
            "duration": 1000  # 到下一动作的时长(ms)
        },
        ...
    ]
    """
    action_sequences[name] = actions
    # 保存到文件
    save_actions_to_file()
    return {"success": True, "name": name, "count": len(actions)}

@app.get("/api/action/list")
async def api_list_actions():
    """获取所有动作序列列表"""
    return {
        "sequences": {
            name: {"count": len(actions)}
            for name, actions in action_sequences.items()
        }
    }

@app.get("/api/action/get/{name}")
async def api_get_action(name: str):
    """获取指定动作序列"""
    if name in action_sequences:
        return {"success": True, "name": name, "actions": action_sequences[name]}
    return {"success": False, "error": "Action not found"}

@app.delete("/api/action/delete/{name}")
async def api_delete_action(name: str):
    """删除动作序列"""
    if name in action_sequences:
        del action_sequences[name]
        save_actions_to_file()
        return {"success": True}
    return {"success": False, "error": "Action not found"}

@app.post("/api/action/play/{name}")
async def api_play_action(name: str, loop: bool = False):
    """播放动作序列"""
    if name not in action_sequences:
        return {"success": False, "error": "Action not found"}
    
    asyncio.create_task(play_action_sequence(name, loop))
    return {"success": True, "name": name}

async def play_action_sequence(name: str, loop: bool = False):
    """异步播放动作序列"""
    if name not in action_sequences:
        return
    
    actions = action_sequences[name]
    
    while True:
        for action in actions:
            # 执行该动作中的所有舵机设置
            servos = action.get("servos", {})
            duration = action.get("duration", 1000)
            
            # 并发发送所有舵机命令
            tasks = []
            for ch_str, angle in servos.items():
                ch = int(ch_str)
                tasks.append(set_servo(ch, angle))
            
            await asyncio.gather(*tasks)
            
            # 广播当前动作状态
            await broadcast_message({
                "type": "action_status",
                "name": name,
                "action": action
            })
            
            # 等待指定时长
            await asyncio.sleep(duration / 1000.0)
        
        if not loop:
            break
    
    await broadcast_message({
        "type": "action_complete",
        "name": name
    })

# ===== WebSocket实时通信 =====
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # 处理客户端消息
            message = json.loads(data)
            if message.get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
    except Exception:
        pass
    finally:
        connected_clients.remove(websocket)

async def broadcast_message(message: Dict):
    """向所有连接的客户端广播消息"""
    dead = []
    for client in connected_clients:
        try:
            await client.send_text(json.dumps(message))
        except Exception:
            dead.append(client)
    for client in dead:
        connected_clients.remove(client)

# ===== 文件持久化 =====
ACTIONS_FILE = "servo_actions.json"

def save_actions_to_file():
    """保存动作序列到文件"""
    try:
        with open(ACTIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(action_sequences, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[ERROR] 保存动作序列失败: {e}")

def load_actions_from_file():
    """从文件加载动作序列"""
    global action_sequences
    try:
        if os.path.exists(ACTIONS_FILE):
            with open(ACTIONS_FILE, "r", encoding="utf-8") as f:
                action_sequences = json.load(f)
            print(f"[INFO] 加载了 {len(action_sequences)} 个动作序列")
    except Exception as e:
        print(f"[ERROR] 加载动作序列失败: {e}")

# ===== 启动加载 =====
@app.on_event("startup")
async def startup_event():
    load_actions_from_file()

# ===== 静态文件服务 =====
@app.get("/")
async def root():
    return FileResponse("servo_control.html")

if __name__ == "__main__":
    import uvicorn
    print(f"""
╔══════════════════════════════════════════════════════════╗
║   ESP32舵机控制系统                                      ║
║   访问地址: http://localhost:8000                        ║
║   ESP32地址: {ESP32_IP}:{ESP32_PORT}                      ║
║                                                          ║
║   测试连接: http://localhost:8000/test_servo?ch=0&angle=90 ║
╚══════════════════════════════════════════════════════════╝

[提示] 如果无法连接ESP32，请：
1. 确认ESP32已上电并连接到WiFi（查看串口输出的IP）
2. 修改第17行的ESP32_IP为实际IP地址
3. 在浏览器访问测试接口检查连接
    """)
    uvicorn.run(app, host="0.0.0.0", port=8000)

