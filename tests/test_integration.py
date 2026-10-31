"""Integration tests (IT-xx): API + database + WebSocket + AI engine together."""
import time

import numpy as np

from app.ai import synth
from app.ai.engine import encode_frame
from tests.conftest import login

CBD = dict(lat=-25.7479, lon=28.2293)


def cad(client, h, call="CAD-1001", priority=1, **loc):
    return client.post("/api/v1/cad/alerts", headers=h, json={"callId": call, "priority": priority, **(loc or CBD)})


def frame_b64(label, seed=5):
    return encode_frame(synth.sample(label, np.random.default_rng(seed))[0])


def test_it01_login_and_bad_credentials(client):
    assert client.post("/api/v1/auth/login", json={"username": "operator1", "password": "wrongpass"}).status_code == 401
    assert "token" in client.post("/api/v1/auth/login", json={"username": "operator1", "password": "firesight123"}).json()


def test_it02_cad_alert_dispatches_nearest_drone_within_30s(client):
    h, _ = login(client)
    r = cad(client, h, lat=-25.5300, lon=28.1000)               # Soshanguve -> DR-03 is nearest
    body = r.json()
    assert r.status_code == 201 and body["droneId"] == "DR-03" and body["dispatchSeconds"] < 30
    assert client.get("/api/v1/drones", headers=h).json()
    assert [d for d in client.get("/api/v1/drones", headers=h).json() if d["_id"] == "DR-03"][0]["status"] == "en_route"
    assert cad(client, h, "CAD-1002", **CBD).json()["droneId"] == "DR-01"      # second call -> next nearest free drone


def test_it03_security_and_validation_errors(client):
    h, _ = login(client)
    assert client.post("/api/v1/cad/alerts", json={}).status_code == 401
    assert client.get("/api/v1/incidents", headers={"Authorization": "Bearer nope"}).status_code == 401
    hc, _ = login(client, "crew1")
    assert client.post("/api/v1/cad/alerts", headers=hc, json={"callId": "X-1", "priority": 1, **CBD}).status_code == 403
    assert client.get("/api/v1/firefighters", headers=hc).status_code == 403
    assert client.post("/api/v1/cad/alerts", headers=h, json={"callId": "X-2", "priority": 9, **CBD}).status_code == 422
    assert cad(client, h).status_code == 201 and cad(client, h).status_code == 409


def test_it04_no_available_drone_queues_dispatch(client):
    h, _ = login(client)
    client.app.state.db.drones.update_many({}, {"$set": {"battery": 10.0}})
    body = cad(client, h).json()
    assert body["dispatched"] is False and body["dispatchStatus"] == "queued"


def test_it05_telemetry_reaches_dashboard_within_500ms(client):
    h, tok = login(client)
    _, ctok = login(client, "commander1")
    with client.websocket_connect(f"/ws?token={ctok}") as ws:
        lat = -25.75
        t0 = time.time()
        r = client.post("/api/v1/drones/DR-01/telemetry", headers=h,
                        json={"lat": lat, "lon": 28.19, "altitude": 80, "battery": 88, "heading": 45})
        ev = ws.receive_json()
        assert r.status_code == 202 and ev["type"] == "telemetry" and ev["altitude"] == 80 and ev["battery"] == 88
        assert time.time() - t0 < 0.5


def test_it06_ai_analyse_stores_result_and_pushes_events(client):
    h, _ = login(client)
    _, ctok = login(client, "commander1")
    inc = cad(client, h).json()["incidentId"]
    client.post("/api/v1/drones/DR-01/telemetry", headers=h,
                json={"lat": CBD["lat"], "lon": CBD["lon"], "altitude": 80, "battery": 90, "heading": 0, "incidentId": inc})
    with client.websocket_connect(f"/ws?token={ctok}") as ws:
        r = client.post("/api/v1/ai/analyse", headers=h, json={"droneId": "DR-01", "incidentId": inc,
                        "frameBase64": frame_b64(2), "timestamp": time.time()})
        res = r.json()
        assert r.status_code == 200 and res["classification"] == "Critical" and res["inferenceMs"] < 100
        types = [ws.receive_json()["type"] for _ in range(3)]
        assert types == ["detection", "hotspots", "alert"]
    stored = client.app.state.db.telemetry.find_one({"kind": "thermal", "incidentId": inc})
    assert stored["aiResult"]["classification"] == "Critical"
    assert client.get(f"/api/v1/incidents/{inc}", headers=h).json()["maxSeverity"] == 2
    bad = client.post("/api/v1/ai/analyse", headers=h, json={"droneId": "DR-01", "incidentId": inc,
                      "frameBase64": "A" * 40, "timestamp": 1})
    assert bad.status_code == 422


def test_it07_firefighter_gps_and_role_privacy(client):
    hc, ctok = login(client, "crew1")
    _, cmd = login(client, "commander1")
    with client.websocket_connect(f"/ws?token={cmd}") as boss, client.websocket_connect(f"/ws?token={ctok}") as crew:
        t0 = time.time()
        r = client.post("/api/v1/firefighters/FF-01/location", headers=hc, json={"lat": -25.748, "lon": 28.229})
        ev = boss.receive_json()
        assert r.status_code == 202 and ev["type"] == "location" and time.time() - t0 < 5
        ho, _ = login(client)
        client.post("/api/v1/drones/DR-01/telemetry", headers=ho,
                    json={"lat": -25.75, "lon": 28.19, "altitude": 80, "battery": 90, "heading": 0})
        assert boss.receive_json()["type"] == "telemetry"
        h2, _ = login(client, "commander1")
        inc = cad(client, ho).json()["incidentId"]
        client.post("/api/v1/messages", headers=h2, json={"incidentId": inc, "text": "Crew 1 hold position"})
        first_for_crew = crew.receive_json()          # crew never receives location/telemetry, only incident + message
        assert first_for_crew["type"] == "incident"
        assert crew.receive_json()["type"] == "incident"  # dispatch status update
        assert crew.receive_json()["type"] == "message"


def test_it08_command_message_reaches_all_clients(client):
    ho, otok = login(client)
    _, ctok = login(client, "commander1")
    inc = cad(client, ho).json()["incidentId"]
    with client.websocket_connect(f"/ws?token={ctok}") as a, client.websocket_connect(f"/ws?token={otok}") as b:
        client.post("/api/v1/messages", headers=ho, json={"incidentId": inc, "channel": "air", "text": "Drone on scene"})
        for ws in (a, b):
            ev = ws.receive_json()
            assert ev["type"] == "message" and ev["text"] == "Drone on scene" and ev["from"] == "operator1"
    assert client.get(f"/api/v1/messages?incidentId={inc}", headers=ho).json()[0]["channel"] == "air"


def test_it09_close_incident_generates_report_under_5_minutes(client):
    ho, _ = login(client)
    hc, _ = login(client, "commander1")
    inc = cad(client, ho).json()["incidentId"]
    client.post("/api/v1/drones/DR-01/telemetry", headers=ho,
                json={"lat": CBD["lat"], "lon": CBD["lon"], "altitude": 80, "battery": 90, "heading": 0, "incidentId": inc})
    for i, label in enumerate([0, 1, 1, 2]):
        client.post("/api/v1/ai/analyse", headers=ho, json={"droneId": "DR-01", "incidentId": inc,
                    "frameBase64": frame_b64(label, seed=i), "timestamp": time.time()})
    assert client.post(f"/api/v1/incidents/{inc}/close", headers=ho).status_code == 403     # operator cannot close
    t0 = time.time()
    r = client.post(f"/api/v1/incidents/{inc}/close", headers=hc)
    assert r.status_code == 200 and time.time() - t0 < 300
    rep = client.get(f"/api/v1/incidents/{inc}/report", headers=hc).json()
    assert rep["summary"]["framesAnalysed"] == 4 and rep["summary"]["maxSeverity"] == 2 and rep["worstFrame"]
    assert client.post(f"/api/v1/incidents/{inc}/close", headers=hc).status_code == 409


def test_it10_spread_endpoint_uses_incident_hotspots(client):
    ho, _ = login(client)
    inc = cad(client, ho).json()["incidentId"]
    client.post("/api/v1/drones/DR-01/telemetry", headers=ho,
                json={"lat": CBD["lat"], "lon": CBD["lon"], "altitude": 80, "battery": 90, "heading": 0})
    client.post("/api/v1/ai/analyse", headers=ho, json={"droneId": "DR-01", "incidentId": inc,
                "frameBase64": frame_b64(2), "timestamp": time.time()})
    r = client.get(f"/api/v1/incidents/{inc}/spread", headers=ho)
    assert r.status_code == 200 and r.json()["geometry"]["type"] == "Polygon"
    assert r.json()["properties"]["weather"]["source"] in ("simulated", "openweathermap")


def test_it11_hal_simulated_mission_runs_without_hardware(sim_client):
    """FR-10: dispatch -> telemetry -> AI -> report all work with the simulation adapter only."""
    c = sim_client
    ho, _ = login(c)
    hc, _ = login(c, "commander1")
    inc = c.post("/api/v1/cad/alerts", headers=ho, json={"callId": "SIM-1", "priority": 1, **CBD}).json()["incidentId"]
    c.post("/api/v1/sim/start", headers=ho, json={"incidentId": inc, "timeScale": 60})
    deadline = time.time() + 40
    while time.time() < deadline:
        doc = c.get(f"/api/v1/incidents/{inc}", headers=ho).json()
        if doc.get("detections", 0) >= 5 and doc["dispatchStatus"] == "on_scene":
            break
        time.sleep(0.5)
    assert doc["dispatchStatus"] == "on_scene" and doc["detections"] >= 5 and doc["hotspots"]
    assert c.post(f"/api/v1/incidents/{inc}/close", headers=hc).status_code == 200
    time.sleep(1.0)
    assert [d for d in c.get("/api/v1/drones", headers=ho).json() if d["_id"] == doc["droneId"]][0]["status"] == "idle"
    assert c.get(f"/api/v1/incidents/{inc}/report", headers=hc).json()["summary"]["framesAnalysed"] >= 5
