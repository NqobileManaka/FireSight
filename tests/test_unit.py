"""Unit tests (UT-xx)."""
import time

import numpy as np
import pytest
from pydantic import ValidationError

from app import security
from app.ai import synth
from app.ai.engine import AIEngine, decode_frame, encode_frame
from app.geo import haversine_m, latlon_to_pixel, metres_per_pixel, pixel_to_latlon
from app.hal.base import DJIAdapter, DroneAdapter
from app.hal.simulator import FireScenario, SimulatedDrone
from app.models import CadAlert, Telemetry
from app.spread import predict

ENGINE = AIEngine()


def test_ut01_jwt_roundtrip_tamper_expiry():
    tok = security.create_token("u1", "commander")
    assert security.decode_token(tok)["role"] == "commander"
    head, body, sig = tok.split(".")
    assert security.decode_token(f"{head}.{body}x.{sig}") is None
    assert security.decode_token(security.create_token("u1", "crew", ttl=-5)) is None


def test_ut02_password_hashing():
    h = security.hash_password("s3cret-pass")
    assert security.check_password("s3cret-pass", h) and not security.check_password("wrong", h)
    assert "s3cret" not in h


def test_ut03_haversine_known_distance():
    d = haversine_m(-25.7461, 28.1881, -25.8603, 28.1894)      # Pretoria CBD -> Centurion
    assert 12_500 < d < 12_900


def test_ut04_georeference_round_trip():
    lat, lon = -25.75, 28.2
    for px, py in [(10, 12), (32, 32), (55, 40)]:
        la, lo = pixel_to_latlon(px, py, lat, lon, 80)
        x, y = latlon_to_pixel(la, lo, lat, lon, 80)
        assert abs(x - px) < 0.01 and abs(y - py) < 0.01


def test_ut05_request_validation_rejects_bad_input():
    with pytest.raises(ValidationError):
        CadAlert(callId="CAD-1", priority=5, lat=-25.7, lon=28.2)
    with pytest.raises(ValidationError):
        CadAlert(callId="CAD-1", priority=1, lat=-125.7, lon=28.2)
    with pytest.raises(ValidationError):
        Telemetry(lat=-25, lon=28, altitude=900, battery=50, heading=10)
    CadAlert(callId="CAD-1", priority=1, lat=-25.7, lon=28.2)


def test_ut06_cnn_accuracy_on_fresh_synthetic_frames():
    rng = np.random.default_rng(999)
    correct = total = 0
    for label in range(3):
        for _ in range(150):
            frame, _ = synth.sample(label, rng)
            correct += ENGINE.analyse(frame, -25.7, 28.2, 80)["severity"] == label
            total += 1
    assert correct / total >= 0.90, correct / total


def test_ut07_hotspot_georeference_error_under_5m():
    """ETR-04: detected hotspot centroids vs simulator ground truth."""
    errs = []
    scen = FireScenario(-25.7479, 28.2293, seed=3)
    for t in range(0, 60, 3):
        scen.t = t
        frame = scen.frame_for(-25.7479, 28.2293, 80, metres_per_pixel(80))
        res = ENGINE.analyse(frame, -25.7479, 28.2293, 80)
        for h in res["hotspots"]:
            errs.append(min(haversine_m(h["lat"], h["lon"], *p) for p in scen.truth_points()))
    assert errs and np.percentile(errs, 95) < 5.0, np.percentile(errs, 95)


def test_ut08_spread_extends_downwind_and_grows_with_wind():
    calm = predict(-25.75, 28.2, 100, {"windKmh": 5, "windFromDeg": 270, "source": "t"})
    windy = predict(-25.75, 28.2, 100, {"windKmh": 40, "windFromDeg": 270, "source": "t"})
    lons = [c[0] for c in windy["geometry"]["coordinates"][0]]
    assert max(lons) - 28.2 > 28.2 - min(lons)             # wind from the west -> spread east
    assert windy["properties"]["forwardM"] > calm["properties"]["forwardM"]


def test_ut09_hal_adapters():
    assert issubclass(SimulatedDrone, DroneAdapter)
    with pytest.raises(NotImplementedError):
        DJIAdapter()
    d = SimulatedDrone("DR-T", -25.86, 28.19)
    d.goto(-25.80, 28.19, 80)
    for _ in range(2000):
        d.step(1.0)
        if d.arrived():
            break
    assert d.arrived() and d.alt == pytest.approx(80, abs=1) and d.battery < 100


def test_ut10_frame_codec_and_rejection():
    frame = synth.sample(1, np.random.default_rng(1))[0]
    assert np.abs(decode_frame(encode_frame(frame)) - frame).max() < 0.01
    with pytest.raises(Exception):
        decode_frame("bm90IGFuIGltYWdl")
