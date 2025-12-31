from __future__ import annotations

import time
import math
from dataclasses import dataclass
from typing import Optional, Dict, Tuple

import requests

import config
from vision import DetectedTarget


def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def ema(prev: Optional[float], v: float, alpha: float) -> float:
    if prev is None:
        return v
    return prev + alpha * (v - prev)


@dataclass
class ServoCommand:
    p1: int
    p2: int
    p3: int
    p4: int


class Esp32Transport:
    """HTTP transport with deadband (avoid sending tiny jitter commands)."""

    def __init__(self) -> None:
        self.base = config.ESP32_BASE_URL.rstrip("/")
        self.sess = requests.Session()
        self._last_sent: Optional[ServoCommand] = None

    def _changed_enough(self, cmd: ServoCommand) -> bool:
        if self._last_sent is None:
            return True
        d = config.SEND_DEADBAND
        return (
            abs(cmd.p1 - self._last_sent.p1) >= d
            or abs(cmd.p2 - self._last_sent.p2) >= d
            or abs(cmd.p3 - self._last_sent.p3) >= d
            or abs(cmd.p4 - self._last_sent.p4) >= d
        )

    def send_batch(self, cmd: ServoCommand, speed: int = config.SERVO_SPEED, acc: int = config.SERVO_ACC) -> bool:
        # deadband: small changes don't send, eliminates servo micro-shake
        if not self._changed_enough(cmd):
            return True

        url = f"{self.base}/arm/batch"
        params = {
            "p1": cmd.p1,
            "p2": cmd.p2,
            "p3": cmd.p3,
            "p4": cmd.p4,
            "speed": speed,
            "acc": acc,
        }
        try:
            # 更短的超时让控制循环更“利落”（局域网正常情况下会更快返回）
            r = self.sess.get(url, params=params, timeout=0.10)
            ok = (r.status_code == 200)
            if ok:
                self._last_sent = cmd
            return ok
        except requests.RequestException:
            return False


class InteractionController:
    """
    你描述的“机械臂避让手”完整逻辑（HAND 模式）：
    - 2/3 号：始终用手面积控制前后距离，保持 hand_area0。
    - 1 号：当手在画面左/右侧并且靠近时，向相反方向转开（避让）。
           当 1 号已经停在某一侧（手消失后锁住），如果手再次出现在画面里，则 1 号反向转动（min侧->往max；max侧->往min）。
    - 彻底取消 HAND 自动切回 FACE/IDLE：模式只由按键控制。
    """

    def __init__(self) -> None:
        self.mode = "IDLE"

        # baseline
        self.face_area0: Optional[float] = None
        self.hand_area0: Optional[float] = None

        # FACE 成功计数
        self._face_stable = 0

        # FACE smooth / anti-oscillation (only affects FACE; HAND unchanged)
        self._face_ex_ema: Optional[float] = None
        self._face_ey_ema: Optional[float] = None
        self._face_absent_streak = 0

        self._face_area_ema: Optional[float] = None

        # HAND smooth
        self._hand_area_ema: Optional[float] = None
        self._hand_hx_ema: Optional[float] = None

        # HAND presence streaks
        self._hand_seen_streak = 0
        self._hand_absent_streak = 0

        # HAND pan state machine
        # NONE -> AVOIDING (按手左右避让) -> (手消失) HOLD_SIDE
        # HOLD_SIDE + 手重新出现 -> FLIPPING (反向避让) -> (手消失) HOLD_SIDE
        self._hand_pan_state: str = "NONE"   # "NONE" | "AVOIDING" | "HOLD_SIDE" | "FLIPPING"
        self._hand_pan_dir: int = 0          # +1 p1增大(右转) / -1 p1减小(左转)
        self._hand_hold_side: Optional[str] = None  # "MIN" or "MAX"
        self._hand_edge_stuck = 0

        # wiggle
        self._last_wiggle_time = 0.0
        self._wiggle_active = False
        self._wiggle_step_index = 0
        self._wiggle_next_ts = 0.0

        # current smoothed positions
        self.cur = {
            1: config.SERVO_LIMITS[1].mid_v,
            2: config.SERVO_LIMITS[2].mid_v,
            3: config.SERVO_LIMITS[3].mid_v,
            4: config.SERVO_LIMITS[4].mid_v,
        }

        # keep 1/2/3 pose during wiggle
        self.last_target_123 = (self.cur[1], self.cur[2], self.cur[3])

    # ---------- public ----------
    def set_mode(self, mode: str) -> None:
        mode = mode.upper()
        if mode == self.mode:
            return

        self.mode = mode
        self._face_stable = 0

        if mode != "FACE":
            self.face_area0 = None
            self._face_stable = 0
            self._face_ex_ema = None
            self._face_ey_ema = None
            self._face_absent_streak = 0
        self._face_area_ema = None

        if mode != "HAND":
            self.reset_hand_area0()

        # stop wiggle when switching
        self._wiggle_active = False
        self._wiggle_step_index = 0
        self._wiggle_next_ts = 0.0

    def reset_face_area0(self) -> None:
        self.face_area0 = None
        self._face_stable = 0
        self._face_ex_ema = None
        self._face_ey_ema = None
        self._face_absent_streak = 0
        self._face_area_ema = None

    def reset_hand_area0(self) -> None:
        self.hand_area0 = None
        self._hand_area_ema = None
        self._hand_hx_ema = None

        self._hand_seen_streak = 0
        self._hand_absent_streak = 0

        self._hand_pan_state = "NONE"
        self._hand_pan_dir = 0
        self._hand_hold_side = None
        self._hand_edge_stuck = 0

    # ---------- helpers ----------
    def _servo_range_half(self, sid: int) -> float:
        lim = config.SERVO_LIMITS[sid]
        return (lim.max_v - lim.min_v) / 2.0

    def _clamp_servo(self, sid: int, pos: float) -> int:
        lim = config.SERVO_LIMITS[sid]
        return int(clamp(pos, lim.min_v, lim.max_v))

    def _p1_is_center(self, p1: int) -> bool:
        lim1 = config.SERVO_LIMITS[1]
        return abs(p1 - lim1.mid_v) <= config.HAND_P1_CENTER_BAND

    def _p1_side(self, p1: int) -> Optional[str]:
        """Return 'MIN'/'MAX' if p1 is clearly on a side, else None (center)."""
        lim1 = config.SERVO_LIMITS[1]
        if self._p1_is_center(p1):
            return None
        return "MIN" if p1 < lim1.mid_v else "MAX"

    def _p1_near_edge(self, p1: int) -> Optional[str]:
        lim1 = config.SERVO_LIMITS[1]
        if p1 <= lim1.min_v + config.HAND_P1_EDGE_BAND:
            return "MIN"
        if p1 >= lim1.max_v - config.HAND_P1_EDGE_BAND:
            return "MAX"
        return None

    def _maybe_start_wiggle(self) -> None:
        now = time.time()
        if now - self._last_wiggle_time < config.WIGGLE_COOLDOWN_S:
            return
        self._last_wiggle_time = now
        self._wiggle_active = True
        self._wiggle_step_index = 0
        self._wiggle_next_ts = 0.0

    def _wiggle_positions(self) -> Tuple[int, ...]:
        lim4 = config.SERVO_LIMITS[4]
        mid = lim4.mid_v
        d = config.WIGGLE_DELTA
        seq = [mid]
        for _ in range(config.WIGGLE_CYCLES):
            seq += [mid + d, mid - d]
        seq += [mid]
        out = []
        for p in seq:
            out.append(int(clamp(p, lim4.min_v, lim4.max_v)))
        return tuple(out)

    # ---------- update ----------
    def update(
        self,
        scene_mode: str,
        face: Optional[DetectedTarget],
        hand: Optional[DetectedTarget],
        frame_w: int,
        frame_h: int,
    ) -> Tuple[ServoCommand, Dict]:
        debug: Dict = {}

        # 模式完全由外部（按键）决定：无自动切换
        self.set_mode(scene_mode)

        lim1, lim2, lim3, lim4 = (config.SERVO_LIMITS[i] for i in (1, 2, 3, 4))
        t1, t2, t3 = self.cur[1], self.cur[2], self.cur[3]
        t4 = lim4.mid_v

        # 1) wiggle only moves servo4
        if self._wiggle_active:
            t1, t2, t3 = self.last_target_123
            seq = self._wiggle_positions()
            now = time.time()
            if self._wiggle_next_ts == 0.0:
                self._wiggle_next_ts = now
            if now >= self._wiggle_next_ts:
                idx = self._wiggle_step_index
                if idx >= len(seq):
                    self._wiggle_active = False
                else:
                    t4 = seq[idx]
                    self._wiggle_step_index += 1
                    self._wiggle_next_ts = now + config.WIGGLE_STEP_MS / 1000.0

        # 2) normal control
        elif self.mode == "FACE":
            if face is None:
                # 人脸短暂丢帧（YOLO 抖动/遮挡）时：先“保持当前姿态”，避免 1 号舵机来回摆动
                self._face_absent_streak += 1
                self._face_stable = 0

                if self._face_absent_streak <= config.FACE_LOST_HOLD_FRAMES:
                    t1, t2, t3, t4 = self.cur[1], self.cur[2], self.cur[3], lim4.mid_v
                else:
                    t1, t2, t3, t4 = lim1.mid_v, lim2.mid_v, lim3.mid_v, lim4.mid_v
            else:
                self._face_absent_streak = 0

                cx, cy = face.center
                ex = (cx - frame_w / 2.0) / (frame_w / 2.0)  # -1..1
                ey = (cy - frame_h / 2.0) / (frame_h / 2.0)  # -1..1

                # 轻量平滑：保持“跟手一样快”的前提下，压掉抖动导致的反复摆动
                ex0 = float(clamp(ex, -1.0, 1.0))
                ey0 = float(clamp(ey, -1.0, 1.0))
                ex_f = ema(self._face_ex_ema, ex0, config.FACE_XY_EMA_ALPHA)
                ey_f = ema(self._face_ey_ema, ey0, config.FACE_XY_EMA_ALPHA)
                self._face_ex_ema = ex_f
                self._face_ey_ema = ey_f
                # 人脸面积：先做轻量平滑（抑制 YOLO 抖动），再计算前后误差
                area_f = ema(self._face_area_ema, face.area_ratio, config.FACE_AREA_EMA_ALPHA)
                self._face_area_ema = area_f

                if self.face_area0 is None:
                    # 第一次出现人脸就以当前面积为基线
                    self.face_area0 = area_f

                # 当人脸基本居中时，让 A0 缓慢自适应到“当前舒服距离”
                # 这能解决：A0 取值偏差导致“退很远才跟/靠不近就退到极限”
                if abs(ex_f) < config.FACE_AREA0_ADAPT_X and abs(ey_f) < config.FACE_AREA0_ADAPT_Y:
                    self.face_area0 = ema(self.face_area0, area_f, config.FACE_AREA0_ADAPT_ALPHA)

                # 使用 log(area/area0) 让“变近/变远”响应更对称，避免靠近时过于敏感
                ea = math.log(max(area_f, 1e-6) / max(self.face_area0, 1e-6))
                ea = float(clamp(ea, -config.FACE_ERR_CLAMP_FAR, config.FACE_ERR_CLAMP_NEAR))

                ea_cmd = 0.0 if abs(ea) < config.FACE_AREA_ERR_DEADBAND else ea

                # 1号：用“增量跟随 + 死区 + 限幅”，解决频繁左右来回摆动
                if abs(ex_f) < config.FACE_P1_DEADBAND:
                    p1_step = 0.0
                else:
                    p1_step = ex_f * config.FACE_P1_STEP_K * config.K_FACE_X
                    p1_step = float(clamp(p1_step, -config.FACE_P1_STEP_MAX, config.FACE_P1_STEP_MAX))
                t1 = self.cur[1] + p1_step
                # 2/3：前后跟随（与 HAND 的 2/3 方向一致），用“步进 + 限幅”让变化更明显且不容易一下打到极限
                gain_a = config.K_FACE_A_FAR if ea_cmd < 0 else config.K_FACE_A_NEAR
                step_a = ea_cmd * gain_a * self._servo_range_half(2)
                step_a = float(clamp(step_a, -config.FACE_A_STEP_MAX, config.FACE_A_STEP_MAX))

                # 与 HAND 的 2/3 联动方向保持一致：step>0（目标更近）=> 后退；step<0（目标更远）=> 前进
                t2 = self.cur[2] - step_a
                t3 = self.cur[3] + step_a + ey_f * self._servo_range_half(3) * config.K_FACE_Y

                ok = (abs(ex_f) < config.FACE_TOL_X and abs(ey_f) < config.FACE_TOL_Y and abs(ea) < config.FACE_TOL_A)
                self._face_stable = (self._face_stable + 1) if ok else 0
                if self._face_stable >= config.FACE_STABLE_FRAMES:
                    self._face_stable = 0
                    self._maybe_start_wiggle()

                debug.update(
                    {
                        "ex": ex,
                        "ey": ey,
                        "ex_f": ex_f,
                        "ey_f": ey_f,
                        "ea": ea,
                        "ea_cmd": ea_cmd,
                        "step_a": step_a,
                        "area_f": area_f,
                        "p1_step": p1_step,
                        "face_area0": self.face_area0,
                    }
                )

        elif self.mode == "HAND":
            if hand is None:
                self._hand_seen_streak = 0
                self._hand_absent_streak += 1
                self._hand_edge_stuck = 0

                # 手连续消失：认为已避让成功，锁住当前侧边（如果已经在侧边）
                if self._hand_absent_streak >= config.HAND_P1_LOCK_FRAMES:
                    side = self._p1_side(self.cur[1])
                    if side is not None:
                        # ======= 新增：每次“避让成功(进入 HOLD_SIDE)”触发 4号舵机晃动一次 =======
                        if self._hand_pan_state != "HOLD_SIDE" or self._hand_hold_side != side:
                            self._maybe_start_wiggle()
                        # ====================================================================
                        self._hand_pan_state = "HOLD_SIDE"
                        self._hand_hold_side = side
                        self._hand_pan_dir = 0
                    else:
                        self._hand_pan_state = "NONE"
                        self._hand_hold_side = None
                        self._hand_pan_dir = 0

                # 手没了：全部保持（不回中位）
                t1, t2, t3, t4 = self.cur[1], self.cur[2], self.cur[3], lim4.mid_v
                debug["hand_state"] = self._hand_pan_state

            else:
                self._hand_absent_streak = 0
                self._hand_seen_streak += 1

                # --- smooth hx & area ---
                cx, cy = hand.center
                hx = (cx - frame_w / 2.0) / (frame_w / 2.0)  # -1..1
                hx = float(clamp(hx, -1.0, 1.0))
                hx_f = ema(self._hand_hx_ema, hx, config.HAND_HX_EMA_ALPHA)
                self._hand_hx_ema = hx_f

                if self.hand_area0 is None:
                    self.hand_area0 = hand.area_ratio

                area_f = ema(self._hand_area_ema, hand.area_ratio, config.HAND_AREA_EMA_ALPHA)
                self._hand_area_ema = area_f

                err = (area_f - self.hand_area0) / max(1e-6, self.hand_area0)  # >0 近, <0 远

                # 2/3：前后跟随（增量控制，稳）
                err_cmd = 0.0 if abs(err) < config.HAND_AREA_ERR_DEADBAND else err
                step = err_cmd * config.K_HAND_A * self._servo_range_half(2)
                step = float(clamp(step, -config.HAND_A_STEP_MAX, config.HAND_A_STEP_MAX))

                t2 = self.cur[2] - step
                t3 = self.cur[3] + step

                # --- 1号：左右避让 ---
                close_enough = (err > config.HAND_P1_TRIGGER_ERR)  # 只在“靠近”时做避让
                desired_dir = 0
                if close_enough and abs(hx_f) > config.HAND_P1_HX_DEADBAND:
                    # 手在左 => 向右避让（p1+）；手在右 => 向左避让（p1-）
                    desired_dir = 1 if hx_f < 0 else -1

                # 反向触发：只有在“锁住侧边”后手重新出现才触发
                if self._hand_pan_state == "HOLD_SIDE":
                    if self._hand_seen_streak >= config.HAND_P1_REAPPEAR_FRAMES:
                        # 从当前侧边反向避让
                        if self._hand_hold_side == "MIN":
                            self._hand_pan_dir = 1
                        else:
                            self._hand_pan_dir = -1
                        self._hand_pan_state = "FLIPPING"
                        self._hand_edge_stuck = 0

                # 正常避让启动/持续
                if self._hand_pan_state in ("NONE",):
                    if desired_dir != 0:
                        self._hand_pan_state = "AVOIDING"
                        self._hand_pan_dir = desired_dir
                        self._hand_edge_stuck = 0
                elif self._hand_pan_state == "AVOIDING":
                    # 如果仍需要避让：允许在中间区域改变方向；否则保持方向防抖
                    if desired_dir != 0 and self._p1_is_center(self.cur[1]):
                        self._hand_pan_dir = desired_dir
                    # 若不再靠近/不在侧边：停止避让
                    if desired_dir == 0:
                        self._hand_pan_state = "NONE"
                        self._hand_pan_dir = 0
                        self._hand_edge_stuck = 0
                elif self._hand_pan_state == "FLIPPING":
                    # flipping 期间不受 hx 影响：一直按反向走
                    pass

                # 计算 t1（默认保持）
                t1 = self.cur[1]
                if self._hand_pan_state in ("AVOIDING", "FLIPPING") and self._hand_pan_dir != 0:
                    t1 = self.cur[1] + self._hand_pan_dir * config.HAND_P1_STEP

                # 顶边卡死保护：如果已经顶到边界但手仍在画面里且仍靠近，则自动反向
                t1c = self._clamp_servo(1, t1)
                edge = self._p1_near_edge(t1c)
                if edge is not None and close_enough:
                    self._hand_edge_stuck += 1
                    if self._hand_edge_stuck >= config.HAND_P1_EDGE_STUCK_FRAMES:
                        self._hand_edge_stuck = 0
                        # 反向
                        self._hand_pan_dir = -1 if edge == "MAX" else 1
                        self._hand_pan_state = "FLIPPING"
                        t1c = self._clamp_servo(1, self.cur[1] + self._hand_pan_dir * config.HAND_P1_STEP)
                else:
                    self._hand_edge_stuck = 0

                t1 = t1c

                debug.update(
                    {
                        "hx": hx,
                        "hx_f": hx_f,
                        "hand_area": hand.area_ratio,
                        "hand_area_f": area_f,
                        "hand_area0": self.hand_area0,
                        "err": err,
                        "step": step,
                        "close_enough": close_enough,
                        "desired_dir": desired_dir,
                        "p1_state": self._hand_pan_state,
                        "p1_dir": self._hand_pan_dir,
                        "hold_side": self._hand_hold_side,
                    }
                )
                debug["hand_state"] = self._hand_pan_state

        else:
            # IDLE: return mid
            t1, t2, t3, t4 = lim1.mid_v, lim2.mid_v, lim3.mid_v, lim4.mid_v

        # 3) clamp + smoothing
        target = {
            1: self._clamp_servo(1, t1),
            2: self._clamp_servo(2, t2),
            3: self._clamp_servo(3, t3),
            4: self._clamp_servo(4, t4),
        }

        alpha = config.SMOOTH_ALPHA_FACE if self.mode == "FACE" else config.SMOOTH_ALPHA

        for sid in (1, 2, 3, 4):
            self.cur[sid] = int(self.cur[sid] + (target[sid] - self.cur[sid]) * alpha)

        self.last_target_123 = (self.cur[1], self.cur[2], self.cur[3])

        cmd = ServoCommand(self.cur[1], self.cur[2], self.cur[3], self.cur[4])
        debug["mode"] = self.mode
        debug["p"] = (cmd.p1, cmd.p2, cmd.p3, cmd.p4)
        return cmd, debug
