from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional, Tuple, List

import cv2
import numpy as np
from ultralytics import YOLO

import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

import config

# MediaPipe 21-hand-landmark connection pairs (same order as mp.solutions.hands.HAND_CONNECTIONS)
HAND_CONNECTIONS = [
    # Thumb
    (0, 1), (1, 2), (2, 3), (3, 4),
    # Index
    (0, 5), (5, 6), (6, 7), (7, 8),
    # Middle
    (5, 9), (9, 10), (10, 11), (11, 12),
    # Ring
    (9, 13), (13, 14), (14, 15), (15, 16),
    # Pinky
    (13, 17), (17, 18), (18, 19), (19, 20),
    # Palm base
    (0, 17),
]


@dataclass
class DetectedTarget:
    bbox: Tuple[int, int, int, int]          # x1,y1,x2,y2
    center: Tuple[float, float]              # cx,cy (pixel)
    area_ratio: float                        # (w*h)/(W*H)
    label: str                               # 用于 UI
    # If this is a hand target, landmarks contains 21 (x,y) pixel points (MediaPipe hand landmark order).
    landmarks: Optional[List[Tuple[int, int]]] = None


class VisionSystem:
    def __init__(self) -> None:
        self.yolo = YOLO(config.YOLO_MODEL_PATH)
        self.yolo_names = self.yolo.model.names if hasattr(self.yolo, "model") else {}

        base = python.BaseOptions(model_asset_path=config.HAND_MODEL_PATH)
        options = vision.HandLandmarkerOptions(
            base_options=base,
            running_mode=vision.RunningMode.VIDEO,
            num_hands=1,
            min_hand_detection_confidence=0.5,
            min_hand_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self.hand_landmarker = vision.HandLandmarker.create_from_options(options)

        self._ts0 = time.time()

    @staticmethod
    def _bbox_center_area(bbox: Tuple[int, int, int, int], W: int, H: int) -> Tuple[Tuple[float, float], float]:
        x1, y1, x2, y2 = bbox
        w = max(1, x2 - x1)
        h = max(1, y2 - y1)
        cx = x1 + w / 2
        cy = y1 + h / 2
        return (cx, cy), (w * h) / float(W * H)

    def detect_face(self, frame_bgr: np.ndarray) -> Optional[DetectedTarget]:
        """
        说明：你当前 yolov8n.pt 不是专用人脸模型，所以这里做“可用优先”的策略：
        1) 如果 config.FACE_CLASS_IDS 指定了，就按指定过滤
        2) 否则：优先找 label 名称包含 face 的类；再否则优先 person；再否则取最大框
        """
        H, W = frame_bgr.shape[:2]
        results = self.yolo.predict(frame_bgr, verbose=False, conf=config.FACE_CONF_THRES)
        if not results:
            return None
        r0 = results[0]
        if r0.boxes is None or len(r0.boxes) == 0:
            return None

        boxes = r0.boxes
        xyxy = boxes.xyxy.cpu().numpy()
        conf = boxes.conf.cpu().numpy()
        cls = boxes.cls.cpu().numpy().astype(int)

        # 过滤候选
        candidates: List[int] = list(range(len(xyxy)))

        if config.FACE_CLASS_IDS is not None:
            candidates = [i for i in candidates if int(cls[i]) in set(config.FACE_CLASS_IDS)]
            if not candidates:
                return None
        else:
            # 根据 names 找 face / person
            name_map = self.yolo_names if isinstance(self.yolo_names, dict) else {}
            face_ids = [k for k, v in name_map.items() if "face" in str(v).lower()]
            person_ids = [k for k, v in name_map.items() if "person" in str(v).lower()]

            if face_ids:
                c2 = [i for i in candidates if int(cls[i]) in set(face_ids)]
                if c2:
                    candidates = c2
            elif person_ids:
                c2 = [i for i in candidates if int(cls[i]) in set(person_ids)]
                if c2:
                    candidates = c2

        # 选一个最稳定：优先最大面积，再看置信度
        best_i = None
        best_score = -1.0
        for i in candidates:
            x1, y1, x2, y2 = xyxy[i].tolist()
            area = max(0.0, (x2 - x1) * (y2 - y1))
            score = area * 1.0 + float(conf[i]) * 1000.0
            if score > best_score:
                best_score = score
                best_i = i

        if best_i is None:
            return None

        x1, y1, x2, y2 = [int(v) for v in xyxy[best_i].tolist()]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(W - 1, x2), min(H - 1, y2)
        bbox = (x1, y1, x2, y2)
        center, area_ratio = self._bbox_center_area(bbox, W, H)

        cls_id = int(cls[best_i])
        cls_name = str(self.yolo_names.get(cls_id, f"id{cls_id}")) if isinstance(self.yolo_names, dict) else f"id{cls_id}"
        label = f"YOLO[{cls_id}:{cls_name}] conf={conf[best_i]:.2f}"

        return DetectedTarget(bbox=bbox, center=center, area_ratio=area_ratio, label=label)

    def detect_hand(self, frame_bgr: np.ndarray) -> Optional[DetectedTarget]:
        H, W = frame_bgr.shape[:2]
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

        ts_ms = int((time.time() - self._ts0) * 1000.0)
        res = self.hand_landmarker.detect_for_video(mp_image, ts_ms)

        if res is None or not res.hand_landmarks:
            return None

        lms = res.hand_landmarks[0]  # 只取一只手
        xs = [lm.x for lm in lms]
        ys = [lm.y for lm in lms]
        x1n, x2n = max(0.0, min(xs)), min(1.0, max(xs))
        y1n, y2n = max(0.0, min(ys)), min(1.0, max(ys))

        x1, y1 = int(x1n * W), int(y1n * H)
        x2, y2 = int(x2n * W), int(y2n * H)
        bbox = (x1, y1, x2, y2)
        center, area_ratio = self._bbox_center_area(bbox, W, H)
        label = f"Hand area={area_ratio:.3f}"

        # Landmarks for skeleton visualization (pixel coords)
        pts: List[Tuple[int, int]] = []
        for lm in lms:
            nx = 0.0 if lm.x < 0.0 else 1.0 if lm.x > 1.0 else lm.x
            ny = 0.0 if lm.y < 0.0 else 1.0 if lm.y > 1.0 else lm.y
            pts.append((int(nx * W), int(ny * H)))

        return DetectedTarget(bbox=bbox, center=center, area_ratio=area_ratio, label=label, landmarks=pts)

    @staticmethod
    def draw_hand_skeleton(frame: np.ndarray, pts: List[Tuple[int, int]],
                           point_color=(0, 255, 255), line_color=(0, 255, 255)) -> None:
        # pts should be 21 points in MediaPipe hand landmark order.
        if not pts or len(pts) < 21:
            return

        # Draw connections
        for a, b in HAND_CONNECTIONS:
            x1, y1 = pts[a]
            x2, y2 = pts[b]
            cv2.line(frame, (x1, y1), (x2, y2), line_color, 2, cv2.LINE_AA)

        # Draw points
        for (x, y) in pts:
            cv2.circle(frame, (x, y), 3, point_color, -1, cv2.LINE_AA)

    @staticmethod
    def draw_target(frame: np.ndarray, target: DetectedTarget, color=(0, 255, 0)) -> None:
        x1, y1, x2, y2 = target.bbox
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        cx, cy = int(target.center[0]), int(target.center[1])
        cv2.circle(frame, (cx, cy), 4, color, -1)
        cv2.putText(frame, target.label, (x1, max(15, y1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)

        # If this is a hand target with landmarks, draw skeleton overlay
        if getattr(target, "landmarks", None):
            VisionSystem.draw_hand_skeleton(frame, target.landmarks)
