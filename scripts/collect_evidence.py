"""Collect measured evidence used in the Assignment 3 document -> artifacts/evidence.json"""
import json, os, subprocess, time, xml.etree.ElementTree as ET
os.environ["FIRESIGHT_NO_AUTOAPP"] = "1"
import numpy as np, mongomock
from fastapi.testclient import TestClient
from app.main import create_app
from app.ai import synth
from app.ai.engine import AIEngine, encode_frame
from app.geo import haversine_m, metres_per_pixel
from app.hal.simulator import FireScenario

ev = {}
# ETR-04 georeference error
eng = AIEngine(); errs = []
for seed in range(4):
    scen = FireScenario(-25.7479, 28.2293, seed=seed)
    for alt in (60, 80, 100):
        for t in range(0, 60, 2):
            scen.t = t
            f = scen.frame_for(-25.7479, 28.2293, alt, metres_per_pixel(alt))
            for h in eng.analyse(f, -25.7479, 28.2293, alt)["hotspots"]:
                errs.append((alt, min(haversine_m(h["lat"], h["lon"], *p) for p in scen.truth_points())))
e = np.array([x[1] for x in errs])
ev["georef"] = {"n": len(e), "p50": round(float(np.percentile(e, 50)), 2), "p95": round(float(np.percentile(e, 95)), 2), "max": round(float(e.max()), 2),
                "by_alt": {str(a): {"n": int(sum(1 for x in errs if x[0] == a)), "p95": round(float(np.percentile([x[1] for x in errs if x[0] == a], 95)), 2)} for a in (60, 80, 100)}}
# API examples
c = TestClient(create_app(db=mongomock.MongoClient()["firesight"], sim_autostart=False))
tok = lambda u: {"Authorization": "Bearer " + c.post("/api/v1/auth/login", json={"username": u, "password": "firesight123"}).json()["token"]}
op = tok("operator1")
ex = {}
r = c.post("/api/v1/cad/alerts", headers=op, json={"callId": "CAD-2026-0930-01", "priority": 1, "lat": -25.7479, "lon": 28.2293, "description": "Structure fire"})
ex["cad_ok"] = {"status": r.status_code, "body": r.json()}
r = c.post("/api/v1/cad/alerts", headers=op, json={"callId": "CAD-2026-0930-01", "priority": 1, "lat": -25.7479, "lon": 28.2293}); ex["cad_dup"] = {"status": r.status_code, "body": r.json()}
r = c.post("/api/v1/cad/alerts", headers=op, json={"callId": "CAD-X", "priority": 7, "lat": -25.7, "lon": 28.2}); ex["cad_invalid"] = {"status": r.status_code, "body": {"detail0": r.json()["detail"][0]["msg"] if "detail" in r.json() else r.json()}}
r = c.post("/api/v1/cad/alerts", json={}); ex["no_token"] = {"status": r.status_code, "body": r.json()}
r = c.post("/api/v1/cad/alerts", headers=tok("crew1"), json={"callId": "CAD-Y", "priority": 1, "lat": -25.7, "lon": 28.2}); ex["wrong_role"] = {"status": r.status_code, "body": r.json()}
c.post("/api/v1/drones/DR-01/telemetry", headers=op, json={"lat": -25.7479, "lon": 28.2293, "altitude": 80, "battery": 90, "heading": 0})
fr = encode_frame(synth.sample(2, np.random.default_rng(5))[0])
r = c.post("/api/v1/ai/analyse", headers=op, json={"droneId": "DR-01", "incidentId": "INC-0001", "frameBase64": fr, "timestamp": time.time()})
b = r.json(); b["hotspots"] = [{k: (round(v, 6) if isinstance(v, float) else v) for k, v in h.items()} for h in b["hotspots"]]
ex["analyse_ok"] = {"status": r.status_code, "body": b}
r = c.post("/api/v1/ai/analyse", headers=op, json={"droneId": "DR-01", "incidentId": "INC-0001", "frameBase64": "A" * 40, "timestamp": 1}); ex["analyse_bad"] = {"status": r.status_code, "body": r.json()}
r = c.get("/api/v1/incidents/INC-0001/spread", headers=op); p = r.json()["properties"]; ex["spread"] = {"status": r.status_code, "properties": p}
ev["api_examples"] = ex
# junit
root = ET.parse("artifacts/junit.xml").getroot()
cases = []
for tc in root.iter("testcase"):
    cases.append({"name": tc.get("name"), "file": tc.get("classname").split(".")[-1], "time": float(tc.get("time")),
                  "status": "fail" if tc.find("failure") is not None or tc.find("error") is not None else "pass"})
ev["tests"] = cases
ev["coverage"] = json.load(open("artifacts/coverage.json"))["totals"]["percent_covered"]
loc = {}
for d, pat in [("app", "*.py"), ("app/static", "*.js"), ("app/static", "index.html"), ("tests", "*.py"), ("scripts", "*.py")]:
    out = subprocess.run(f"cat {d}/{pat} 2>/dev/null | wc -l", shell=True, capture_output=True, text=True).stdout.strip()
    loc[f"{d}/{pat}"] = int(out)
ev["loc"] = loc
ev["versions"] = json.loads(subprocess.run("pip list --format=json", shell=True, capture_output=True, text=True).stdout)
ev["versions"] = {p["name"].lower(): p["version"] for p in ev["versions"] if p["name"].lower() in ("fastapi","uvicorn","torch","pymongo","mongomock","pydantic","opencv-python-headless","numpy","pytest","websockets","httpx","playwright")}
json.dump(ev, open("artifacts/evidence.json", "w"), indent=1)
print(json.dumps({k: ev[k] for k in ("georef", "coverage", "loc")}, indent=1)); print(json.dumps(ex["cad_ok"]), json.dumps(ex["analyse_ok"])[:400], ex["cad_invalid"], ex["wrong_role"], ex["analyse_bad"]); print(len(cases), "tests"); print(ev["versions"])
