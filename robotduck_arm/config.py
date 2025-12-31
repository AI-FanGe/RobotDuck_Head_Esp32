from dataclasses import dataclass
from pathlib import Path

# ★ 使用相对路径，自动获取当前文件所在目录
PROJECT_DIR = Path(__file__).parent.resolve()
MODELS_DIR = PROJECT_DIR / "models"

# ======= ESP32 控制地址（把 IP 改成串口里看到的 ESP32 IP）=======
ESP32_BASE_URL = "http://192.168.2.10"  # <-- ESP32 实际 IP

# ======= 模型路径 =======
YOLO_MODEL_PATH = str(MODELS_DIR / "yolov11n-face.pt")
HAND_MODEL_PATH = str(MODELS_DIR / "hand_landmarker.task")

# ======= YOLO 人脸类别（你目前不确定，就先 None；UI 会把 cls/id/name 打出来）=======
FACE_CLASS_IDS = None  # 例如 [0]；暂时先 None

# ======= 舵机标定（你已验证）=======
@dataclass
class ServoLimit:
    min_v: int
    mid_v: int
    max_v: int

SERVO_LIMITS = {
    1: ServoLimit(1050, 2025, 3000),
    2: ServoLimit(1500, 2047, 2500),
    3: ServoLimit(1500, 2047, 2500),
    4: ServoLimit(1800, 2047, 2300),
}

# ======= 控制频率与平滑 =======
# ★ 降低参数防止振荡
CONTROL_HZ = 25                 # 下发频率（降低，减少振荡）
SMOOTH_ALPHA = 0.45             # 越大越跟手，越小越稳（降低防抖）
SMOOTH_ALPHA_FACE = 0.50        # 仅用于 FACE（降低防抖）
SEND_DEADBAND = 8               # pos 变化小于该值就不下发（增大防抖）

# ======= 舵机运动学参数（HTTP batch 指令参数）=======
# firmware 侧 speed 被限制在 50~2000；acc 被限制在 0~255。
SERVO_SPEED = 2000              # 越大越快
SERVO_ACC = 200                 # 越大启动越猛（更“灵敏”），太大可能更抖

# ======= 场景 A（跟随人脸）参数 =======
FACE_CONF_THRES = 0.25

# 误差容忍（用于判定“成功跟随”，触发晃头）
FACE_TOL_X = 0.08
FACE_TOL_Y = 0.10
FACE_TOL_A = 0.15
FACE_STABLE_FRAMES = 8          # 连续满足多少帧算成功

# 比例增益（你后续会调参；先给一个稳的默认）
K_FACE_X = 0.85                 # 1号左右
K_FACE_A = 0.90                 # 2/3 距离联动
K_FACE_Y = 0.65                 # 3号高度微调

# FACE 跟随稳定性（只影响 FACE 模式；不会改变 HAND 的任何逻辑/手感）
# ★ 降低参数防止振荡
FACE_XY_EMA_ALPHA = 0.40         # 越大越跟随（更快），越小越稳（降低防抖）
FACE_P1_DEADBAND = 0.08          # |ex| 小于该值认为在中间，不动 1 号（增大死区防抖）
FACE_P1_STEP_K = 120             # 1号每帧步进系数（降低防抖）
FACE_P1_STEP_MAX = 80            # 1号单帧最大步进（pos）（降低防抖）
FACE_LOST_HOLD_FRAMES = 10       # 人脸短暂丢帧时先保持 N 帧（增加稳定性）

# 人脸前后距离控制（只影响 FACE；HAND 不变）
# ★ 降低参数防止振荡
FACE_AREA_EMA_ALPHA = 0.35        # 人脸面积平滑（降低防抖）
FACE_AREA0_ADAPT_ALPHA = 0.05     # A0 缓慢自适应
FACE_AREA0_ADAPT_X = 0.15         # 只有 |ex_f| 小于该值才允许自适应
FACE_AREA0_ADAPT_Y = 0.18         # 只有 |ey_f| 小于该值才允许自适应
FACE_AREA_ERR_DEADBAND = 0.08     # 死区（增大防抖）
FACE_ERR_CLAMP_FAR = 0.40         # 人脸变远时的最大误差（降低）
FACE_ERR_CLAMP_NEAR = 0.30        # 人脸变近时的最大误差（降低）
K_FACE_A_FAR = 1.20               # 前进响应强度（降低）
K_FACE_A_NEAR = 0.80              # 后退响应强度（降低）
FACE_A_STEP_MAX = 100             # 2/3 号单帧最大步进（降低防抖）

# ======= 场景 B（手交互：前后跟随 + 左右避让）参数 =======
# 目标：
# 1) 2/3 号：用“手面积”维持距离（手越大=>后退；手越小=>前进），尽量保持进入 HAND 时的初始面积 hand_area0
# 2) 1 号：当手在画面左/右侧并且靠近时，向相反方向转开（避让）
#    - 手在左侧靠近 => 1号往右转（p1 增大）
#    - 手在右侧靠近 => 1号往左转（p1 减小）
#    - 当 1 号已在某一侧“停住”并且手再次出现在画面中，会自动反向转动（min侧=>往max；max侧=>往min）

# 手面积控制（EMA + 死区）
HAND_AREA_EMA_ALPHA = 0.55          # 越大越灵敏（更快），越小越稳（更慢）
HAND_HX_EMA_ALPHA = 0.45            # 手中心点 hx 平滑（用于决定避让方向）
HAND_AREA_ERR_DEADBAND = 0.05       # 相对误差 |(A-A0)/A0| < 5% 不动作，避免抖动
K_HAND_A = 1.25                     # 手面积 -> 2/3 号联动强度（更快响应）
HAND_A_STEP_MAX = 140               # 单次更新允许的最大步进（pos），防止震荡

# 1号避让触发条件（只在“手靠近”时才避让）
HAND_P1_TRIGGER_ERR = 0.10          # (A-A0)/A0 > 0.10 认为手在靠近，允许 1号避让
HAND_P1_HX_DEADBAND = 0.12          # |hx| 小于该值，认为在画面中央，不做左右避让（只做2/3前后）
HAND_P1_STEP = 95                   # 1号每帧转动步进（pos）（更快避让）

# 1号“停在某一侧”的判定
HAND_P1_CENTER_BAND = 220           # |p1-mid| <= 220 认为在中间区域
HAND_P1_EDGE_BAND = 160             # 距离 min/max <= 160 认为在边侧（用于“停住在某一侧”）

# 手消失后多久算“停住”并锁定侧边（用于之后的反向）
HAND_P1_LOCK_FRAMES = 4             # 手连续丢失 N 帧 -> 认为已避让成功，锁住当前侧边
HAND_P1_REAPPEAR_FRAMES = 3         # 在“锁住侧边”后，手连续出现 N 帧 -> 触发反向避让

# 若已经顶到边界但手仍在画面中，避免卡死：顶边连续若干帧后自动反向
HAND_P1_EDGE_STUCK_FRAMES = 3

# ======= 晃头动画（4号）=======
WIGGLE_DELTA = 120              # 左右摆动幅度（pos）
WIGGLE_STEP_MS = 160            # 每步间隔
WIGGLE_CYCLES = 2               # 来回次数
WIGGLE_COOLDOWN_S = 1.2         # 两次晃头最小间隔

# ======= UI =======
WINDOW_NAME = "RobotDuck Arm (Face/Hand Interaction)"
DRAW_CENTER_CROSS = True
