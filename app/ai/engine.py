"""AI engine: CNN classification + OpenCV hotspot segmentation + georeferencing."""
import base64
import os
import time

import cv2
import numpy as np
import torch

from app.ai.model import ThermalCNN
from app.ai.synth import CLASSES
from app.geo import metres_per_pixel, pixel_to_latlon

WEIGHTS = os.path.join(os.path.dirname(__file__), "weights.pt")
HOT_THRESHOLD = 0.62


def encode_frame(frame: np.ndarray) -> str:
    ok, buf = cv2.imencode(".png", (np.clip(frame, 0, 1) * 255).astype(np.uint8))
    return base64.b64encode(buf.tobytes()).decode()


def decode_frame(b64: str) -> np.ndarray:
    raw = np.frombuffer(base64.b64decode(b64, validate=True), np.uint8)
    img = cv2.imdecode(raw, cv2.IMREAD_GRAYSCALE)
    if img is None or img.shape != (64, 64):
        raise ValueError("frame must be a 64x64 grayscale PNG")
    return img.astype(np.float32) / 255.0


class AIEngine:
    def __init__(self):
        torch.set_num_threads(1)
        self.model = ThermalCNN()
        self.model.load_state_dict(torch.load(WEIGHTS, map_location="cpu"))
        self.model.eval()

    def hotspots(self, frame, drone_lat, drone_lon, altitude, heading=0.0):
        mask = (frame > HOT_THRESHOLD).astype(np.uint8)
        n, _, stats, cents = cv2.connectedComponentsWithStats(mask, 8)
        out = []
        for i in range(1, n):
            area = int(stats[i, cv2.CC_STAT_AREA])
            if area < 3:
                continue
            cx, cy = cents[i]
            lat, lon = pixel_to_latlon(cx, cy, drone_lat, drone_lon, altitude, heading)
            out.append({"lat": lat, "lon": lon, "px": [float(cx), float(cy)], "areaPx": area,
                        "areaM2": round(area * metres_per_pixel(altitude) ** 2, 1)})
        return sorted(out, key=lambda h: -h["areaPx"])

    def analyse(self, frame, drone_lat, drone_lon, altitude, heading=0.0) -> dict:
        t0 = time.perf_counter()
        with torch.no_grad():
            logits = self.model(torch.from_numpy(frame)[None, None])
            probs = torch.softmax(logits, 1)[0]
        cls = int(probs.argmax())
        spots = self.hotspots(frame, drone_lat, drone_lon, altitude, heading) if cls > 0 else []
        return {"classification": CLASSES[cls], "severity": cls, "confidence": round(float(probs[cls]), 4),
                "hotspots": spots, "inferenceMs": round((time.perf_counter() - t0) * 1000, 2)}
