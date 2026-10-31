"""System tests (ST-xx): a real uvicorn process, real sockets, simulated drone via the HAL. Writes artifacts/system_metrics.json."""
import json
import os
import socket
import ssl
import statistics
import subprocess
import sys
import time

import httpx
import psutil
import pytest
from websockets.sync.client import connect

ROOT = os.path.dirname(os.path.dirname(__file__))
METRICS = os.path.join(ROOT, "artifacts", "system_metrics.json")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(port, extra_env=None, extra_args=()):
    env = {**os.environ, "PYTHONPATH": ROOT, "SIM_TIME_SCALE": "30", "SIM_CRITICAL_AFTER_S": "8", **(extra_env or {})}
    env.pop("FIRESIGHT_NO_AUTOAPP", None)
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port), "--log-level", "warning",
                             *extra_args], cwd=ROOT, env=env)
    return proc


def wait_up(url, verify=True, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if httpx.get(url, verify=verify, timeout=1).status_code == 200:
                return
        except Exception:
            time.sleep(0.3)
    raise RuntimeError("server did not start")


def pct(values, p):
    values = sorted(values)
    return values[min(len(values) - 1, int(len(values) * p))]


def test_st01_end_to_end_mission_metrics():
    port = free_port()
    proc = start_server(port)
    try:
        base = f"http://127.0.0.1:{port}"
        wait_up(base + "/api/v1/health")
        tok = lambda u: httpx.post(f"{base}/api/v1/auth/login", json={"username": u, "password": "firesight123"}).json()["token"]
        op, cmd = tok("operator1"), tok("commander1")
        H = lambda t: {"Authorization": f"Bearer {t}"}
        ps = psutil.Process(proc.pid)
        with connect(f"ws://127.0.0.1:{port}/ws?token={cmd}") as ws:
            t0 = time.time()
            r = httpx.post(f"{base}/api/v1/cad/alerts", headers=H(op),
                           json={"callId": "ST-1", "priority": 1, "lat": -25.7479, "lon": 28.2293})
            dispatch_http_ms = (time.time() - t0) * 1000
            inc = r.json()["incidentId"]
            assert r.status_code == 201 and r.json()["dispatched"]
            tel_lat, tel_ts, det_ms, det_ts, classes = [], [], [], [], []
            alert_seen = on_scene_at = None
            ps.cpu_percent(None)
            stream_start = None
            end = time.time() + 45
            while time.time() < end:
                try:
                    ev = json.loads(ws.recv(timeout=2))
                except TimeoutError:
                    continue
                now = time.time()
                if ev["type"] == "incident" and ev.get("dispatchStatus") == "on_scene":
                    on_scene_at = now
                    stream_start = now
                    ps.cpu_percent(None)
                if ev["type"] == "telemetry":
                    tel_lat.append((now - ev["ts"]) * 1000)
                    tel_ts.append(now)
                elif ev["type"] == "detection":
                    det_ms.append(ev["result"]["inferenceMs"])
                    det_ts.append(now)
                    classes.append(ev["result"]["classification"])
                elif ev["type"] == "alert":
                    alert_seen = now
                if stream_start and now - stream_start >= 15:
                    break
            cpu = ps.cpu_percent(None)
            assert on_scene_at, "drone never reached the scene"
        # steady-state rates measured only during the on-scene window
        win_t = [t for t in tel_ts if t >= stream_start]
        win_d = [t for t in det_ts if t >= stream_start]
        tel_rate = (len(win_t) - 1) / (win_t[-1] - win_t[0])
        det_rate = (len(win_d) - 1) / (win_d[-1] - win_d[0])
        t1 = time.time()
        close = httpx.post(f"{base}/api/v1/incidents/{inc}/close", headers=H(cmd))
        close_ms = (time.time() - t1) * 1000
        rep = httpx.get(f"{base}/api/v1/incidents/{inc}/report", headers=H(cmd)).json()
        t2 = time.time()
        page = httpx.get(base + "/")
        metrics = {
            "cad_alert_http_roundtrip_ms": round(dispatch_http_ms, 1),
            "dispatch_seconds_server": httpx.get(f"{base}/api/v1/incidents/{inc}", headers=H(cmd)).json()["dispatchSeconds"],
            "telemetry_events": len(tel_lat), "telemetry_rate_hz": round(tel_rate, 2),
            "telemetry_latency_ms": {"p50": round(statistics.median(tel_lat), 2), "p95": round(pct(tel_lat, .95), 2), "max": round(max(tel_lat), 2)},
            "detections": len(det_ms), "frame_rate_fps": round(det_rate, 2),
            "inference_ms": {"p50": round(statistics.median(det_ms), 2), "p95": round(pct(det_ms, .95), 2), "max": round(max(det_ms), 2)},
            "server_cpu_percent_of_one_core": round(cpu, 1), "cpu_cores_available": psutil.cpu_count(),
            "classes_seen": sorted(set(classes)), "critical_alert_raised": bool(alert_seen),
            "report_generation_ms": rep["generationMs"], "close_request_ms": round(close_ms, 1),
            "report_frames_analysed": rep["summary"]["framesAnalysed"], "report_max_severity": rep["summary"]["maxSeverity"],
            "index_html_bytes": len(page.content),
        }
        os.makedirs(os.path.dirname(METRICS), exist_ok=True)
        json.dump(metrics, open(METRICS, "w"), indent=2)
        print(json.dumps(metrics, indent=2))
        assert close.status_code == 200 and rep["summary"]["framesAnalysed"] > 20
        assert metrics["telemetry_latency_ms"]["p95"] < 500 and metrics["inference_ms"]["p95"] < 100
    finally:
        proc.terminate()
        proc.wait(10)


def test_st02_tls13_in_transit(tmp_path):
    key, crt = tmp_path / "k.pem", tmp_path / "c.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", crt, "-days", "1",
                    "-subj", "/CN=localhost"], check=True, capture_output=True)
    port = free_port()
    proc = start_server(port, extra_args=["--ssl-keyfile", str(key), "--ssl-certfile", str(crt),
                                          "--ssl-version", str(ssl.PROTOCOL_TLS_SERVER)])
    try:
        wait_up(f"https://127.0.0.1:{port}/api/v1/health", verify=False)
        ctx = ssl.create_default_context()
        ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
        ctx.minimum_version = ssl.TLSVersion.TLSv1_3
        with socket.create_connection(("127.0.0.1", port)) as raw, ctx.wrap_socket(raw) as s:
            negotiated = s.version()
        old = ssl.create_default_context()
        old.check_hostname, old.verify_mode = False, ssl.CERT_NONE
        old.maximum_version = ssl.TLSVersion.TLSv1_2
        tls12_refused = False
        try:
            with socket.create_connection(("127.0.0.1", port)) as raw, old.wrap_socket(raw):
                pass
        except ssl.SSLError:
            tls12_refused = True
        m = json.load(open(METRICS)) if os.path.exists(METRICS) else {}
        m["tls_negotiated"] = negotiated
        m["tls12_only_client_refused"] = tls12_refused
        json.dump(m, open(METRICS, "w"), indent=2)
        assert negotiated == "TLSv1.3"
    finally:
        proc.terminate()
        proc.wait(10)
