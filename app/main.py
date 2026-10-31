"""FireSight FastAPI backend: REST + WebSocket, JWT/RBAC, dispatch, AI ingest, spread prediction, reports."""
import asyncio
import os
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request

from app import db as dbmod
from app.ai.engine import AIEngine, decode_frame, encode_frame
from app.geo import haversine_m
from app.hal.simulator import FireScenario, SimulatedDrone
from app.models import (AnalyseRequest, CadAlert, LoginRequest, Location, Message, SimStart, Telemetry)
from app.report import build_report
from app.security import check_password, create_token, decode_token
from app.spread import get_weather, predict

CREW_BLOCKED = {"telemetry", "detection", "hotspots", "location", "spread"}   # privacy: crew see commands only
_engine: AIEngine | None = None


def engine() -> AIEngine:
    global _engine
    if _engine is None:
        _engine = AIEngine()
    return _engine


class Hub:
    """WebSocket connection registry with role-based event filtering."""

    def __init__(self):
        self.clients: list[tuple[WebSocket, str]] = []

    async def broadcast(self, event: dict):
        for ws, role in list(self.clients):
            if role == "crew" and event["type"] in CREW_BLOCKED:
                continue
            try:
                await ws.send_json(event)
            except Exception:
                self.clients = [c for c in self.clients if c[0] is not ws]


def create_app(db=None, sim_autostart: bool | None = None) -> FastAPI:
    db = db if db is not None else dbmod.get_db()
    dbmod.seed(db)
    hub = Hub()
    autostart = (os.getenv("SIM_MODE", "1") == "1") if sim_autostart is None else sim_autostart
    missions: dict[str, asyncio.Task] = {}

    @asynccontextmanager
    async def lifespan(_app):
        yield
        for task in missions.values():
            task.cancel()

    app = FastAPI(title="FireSight API", version="1.0.0", lifespan=lifespan)
    app.state.db, app.state.hub, app.state.missions = db, hub, missions

    # ---------------------------------------------------------------- errors / auth
    @app.exception_handler(HTTPException)
    async def http_err(_r: Request, exc: HTTPException):
        return JSONResponse({"error": exc.detail, "status": exc.status_code}, status_code=exc.status_code)

    def auth(*roles):
        def dep(authorization: str | None = Header(default=None)):
            if not authorization or not authorization.startswith("Bearer "):
                raise HTTPException(401, "missing bearer token")
            claims = decode_token(authorization[7:])
            if not claims:
                raise HTTPException(401, "invalid or expired token")
            if roles and claims["role"] not in roles:
                raise HTTPException(403, f"role '{claims['role']}' not permitted")
            return claims
        return dep

    # ---------------------------------------------------------------- core helpers
    def next_incident_id() -> str:
        doc = db.counters.find_one_and_update({"_id": "incident"}, {"$inc": {"n": 1}}, upsert=True, return_document=True)
        return f"INC-{doc['n']:04d}"

    def nearest_available_drone(lat, lon):
        best, best_d = None, 1e12
        # Production: db.drones.find({location: {$near: ...}}) on the 2dsphere index (Atlas). Haversine keeps
        # the same behaviour on the in-memory store used for tests.
        for d in db.drones.find({"status": "idle", "battery": {"$gte": 30}}):
            dist = haversine_m(lat, lon, d["location"]["coordinates"][1], d["location"]["coordinates"][0])
            if dist < best_d:
                best, best_d = d, dist
        return best, best_d

    async def dispatch(incident: dict) -> bool:
        lon, lat = incident["location"]["coordinates"]
        drone, dist = nearest_available_drone(lat, lon)
        if not drone:
            db.incidents.update_one({"_id": incident["_id"]}, {"$set": {"dispatchStatus": "queued"}})
            await hub.broadcast({"type": "incident", "incidentId": incident["_id"], "dispatchStatus": "queued"})
            return False
        db.drones.update_one({"_id": drone["_id"]}, {"$set": {"status": "en_route", "incidentId": incident["_id"]}})
        secs = round(time.time() - incident["reportedAt"], 3)
        db.incidents.update_one({"_id": incident["_id"]}, {"$set": {
            "droneId": drone["_id"], "dispatchStatus": "en_route", "dispatchSeconds": secs, "distanceM": round(dist)}})
        await hub.broadcast({"type": "incident", "incidentId": incident["_id"], "dispatchStatus": "en_route",
                             "droneId": drone["_id"], "distanceM": round(dist)})
        if autostart:
            start_mission(drone["_id"], incident["_id"], float(os.getenv("SIM_TIME_SCALE", 10)))
        return True

    async def ingest_telemetry(drone_id: str, t: Telemetry, status: str | None = None):
        now = time.time()
        upd = {"location": dbmod.point(t.lat, t.lon), "altitude": t.altitude, "battery": t.battery,
               "heading": t.heading, "updatedAt": now}
        if status:
            upd["status"] = status
        db.drones.update_one({"_id": drone_id}, {"$set": upd})
        db.telemetry.insert_one({"kind": "position", "droneId": drone_id, "incidentId": t.incidentId, "ts": now,
                                 "gps": dbmod.point(t.lat, t.lon), "altitude": t.altitude, "battery": t.battery,
                                 "heading": t.heading})
        await hub.broadcast({"type": "telemetry", "droneId": drone_id, "lat": t.lat, "lon": t.lon, "altitude": t.altitude,
                             "battery": round(t.battery, 1), "heading": round(t.heading, 1), "status": status, "ts": now})

    async def analyse_frame(drone_id: str, incident_id: str, frame_b64: str) -> dict:
        drone = db.drones.find_one({"_id": drone_id})
        if not drone:
            raise HTTPException(404, "unknown drone")
        if not db.incidents.find_one({"_id": incident_id}):
            raise HTTPException(404, "unknown incident")
        try:
            frame = decode_frame(frame_b64)
        except Exception:
            raise HTTPException(422, "frameBase64 must be a base64 64x64 grayscale PNG")
        lon, lat = drone["location"]["coordinates"]
        result = await asyncio.to_thread(engine().analyse, frame, lat, lon, max(drone.get("altitude", 80.0), 1.0),
                                         drone.get("heading", 0.0))
        now = time.time()
        db.telemetry.insert_one({"kind": "thermal", "droneId": drone_id, "incidentId": incident_id, "ts": now,
                                 "gps": drone["location"], "frameBase64": frame_b64, "aiResult": result})
        inc = db.incidents.find_one({"_id": incident_id})
        first_crit = result["severity"] == 2 and inc.get("maxSeverity", 0) < 2
        db.incidents.update_one({"_id": incident_id}, {
            "$set": {"hotspots": result["hotspots"], "maxSeverity": max(inc.get("maxSeverity", 0), result["severity"]),
                     "lastClassification": result["classification"], "lastDetectionAt": now},
            "$inc": {"detections": 1}})
        await hub.broadcast({"type": "detection", "incidentId": incident_id, "droneId": drone_id, "ts": now,
                             "frameBase64": frame_b64, "result": result})
        if result["hotspots"]:
            await hub.broadcast({"type": "hotspots", "incidentId": incident_id, "hotspots": result["hotspots"], "ts": now})
        if first_crit:
            await hub.broadcast({"type": "alert", "level": "critical", "incidentId": incident_id, "ts": now})
        return result

    # ---------------------------------------------------------------- simulation (HAL) mission
    def start_mission(drone_id: str, incident_id: str, time_scale: float):
        if drone_id in missions and not missions[drone_id].done():
            return
        missions[drone_id] = asyncio.create_task(mission(drone_id, incident_id, time_scale))

    async def mission(drone_id: str, incident_id: str, time_scale: float):
        d = db.drones.find_one({"_id": drone_id})
        inc = db.incidents.find_one({"_id": incident_id})
        lon, lat = inc["location"]["coordinates"]
        home_lon, home_lat = d["homeLocation"]["coordinates"]
        adapter = SimulatedDrone(drone_id, home_lat, home_lon, d["battery"])
        adapter.scenario = FireScenario(lat, lon, seed=hash(incident_id) & 0xFFFF, critical_after_s=float(os.getenv("SIM_CRITICAL_AFTER_S", 25)))
        adapter.goto(lat, lon, 80.0)
        tick, on_scene = 0.1, False
        next_at = time.monotonic()
        try:
            while True:
                cur = db.incidents.find_one({"_id": incident_id})
                if not cur or cur["status"] != "open":
                    break
                s = adapter.step(tick * time_scale, real_dt=tick)
                if adapter.arrived() and not on_scene:
                    on_scene = True
                    db.incidents.update_one({"_id": incident_id}, {"$set": {"dispatchStatus": "on_scene"}})
                    await hub.broadcast({"type": "incident", "incidentId": incident_id, "dispatchStatus": "on_scene"})
                await ingest_telemetry(drone_id, Telemetry(lat=s.lat, lon=s.lon, altitude=s.altitude, battery=s.battery,
                                                           heading=s.heading, incidentId=incident_id),
                                       "on_scene" if on_scene else "en_route")
                frame = adapter.thermal_frame()
                if frame is not None:
                    await analyse_frame(drone_id, incident_id, encode_frame(frame))
                next_at += tick                       # fixed-rate schedule: compensates for processing time
                await asyncio.sleep(max(0.0, next_at - time.monotonic()))
        finally:
            db.drones.update_one({"_id": drone_id}, {"$set": {
                "status": "idle", "location": d["homeLocation"], "altitude": 0.0, "incidentId": None}})
            queued = db.incidents.find_one({"dispatchStatus": "queued", "status": "open"})
            if queued:
                asyncio.create_task(dispatch(queued))

    # ---------------------------------------------------------------- REST
    @app.get("/api/v1/health")
    def health():
        return {"status": "ok", "time": time.time()}

    @app.post("/api/v1/auth/login")
    def login(body: LoginRequest):
        user = db.users.find_one({"_id": body.username})
        if not user or not check_password(body.password, user["passwordHash"]):
            raise HTTPException(401, "invalid credentials")
        return {"token": create_token(body.username, user["role"]), "role": user["role"], "user": body.username}

    @app.post("/api/v1/cad/alerts", status_code=201)
    async def cad_alert(body: CadAlert, _u=Depends(auth("operator", "admin"))):
        if db.incidents.find_one({"callId": body.callId}):
            raise HTTPException(409, "duplicate CAD call id")
        inc = {"_id": next_incident_id(), "callId": body.callId, "priority": body.priority,
               "description": body.description, "status": "open", "location": dbmod.point(body.lat, body.lon),
               "reportedAt": time.time(), "detections": 0, "maxSeverity": 0, "hotspots": [], "dispatchStatus": "pending"}
        db.incidents.insert_one(inc)
        await hub.broadcast({"type": "incident", "incidentId": inc["_id"], "status": "open", "lat": body.lat, "lon": body.lon,
                             "priority": body.priority, "callId": body.callId})
        ok = await dispatch(inc)
        cur = db.incidents.find_one({"_id": inc["_id"]})
        return {"incidentId": inc["_id"], "dispatched": ok, "droneId": cur.get("droneId"),
                "dispatchSeconds": cur.get("dispatchSeconds"), "distanceM": cur.get("distanceM"),
                "dispatchStatus": cur["dispatchStatus"]}

    @app.get("/api/v1/incidents")
    def incidents(_u=Depends(auth())):
        return list(db.incidents.find({}, {"hotspots": 0}).sort("reportedAt", -1))

    @app.get("/api/v1/incidents/{incident_id}")
    def incident(incident_id: str, _u=Depends(auth())):
        doc = db.incidents.find_one({"_id": incident_id})
        if not doc:
            raise HTTPException(404, "unknown incident")
        return doc

    @app.post("/api/v1/incidents/{incident_id}/close")
    async def close(incident_id: str, _u=Depends(auth("commander", "admin"))):
        doc = db.incidents.find_one({"_id": incident_id})
        if not doc:
            raise HTTPException(404, "unknown incident")
        if doc["status"] == "closed":
            raise HTTPException(409, "incident already closed")
        db.incidents.update_one({"_id": incident_id}, {"$set": {"status": "closed", "closedAt": time.time()}})
        doc = db.incidents.find_one({"_id": incident_id})
        report = await asyncio.to_thread(build_report, db, doc)
        if doc.get("droneId") and not autostart:       # real/manual adapters are freed here; missions free themselves
            db.drones.update_one({"_id": doc["droneId"]}, {"$set": {"status": "idle"}})
        await hub.broadcast({"type": "incident", "incidentId": incident_id, "status": "closed", "reportId": report["_id"]})
        return {"incidentId": incident_id, "reportId": report["_id"], "generationMs": report["generationMs"]}

    @app.get("/api/v1/incidents/{incident_id}/report")
    def get_report(incident_id: str, _u=Depends(auth("commander", "operator", "admin"))):
        rep = db.reports.find_one({"incidentId": incident_id})
        if not rep:
            raise HTTPException(404, "no report for incident")
        return rep

    @app.get("/api/v1/incidents/{incident_id}/spread")
    def spread(incident_id: str, slope_deg: float = Query(default=0.0, ge=0, le=45),
               _u=Depends(auth("commander", "operator", "admin"))):
        doc = db.incidents.find_one({"_id": incident_id})
        if not doc:
            raise HTTPException(404, "unknown incident")
        spots = doc.get("hotspots") or []
        if spots:
            lat = sum(h["lat"] for h in spots) / len(spots)
            lon = sum(h["lon"] for h in spots) / len(spots)
            area = sum(h["areaM2"] for h in spots)
        else:
            lon, lat = doc["location"]["coordinates"]
            area = 10.0
        return predict(lat, lon, area, get_weather(lat, lon), slope_deg=slope_deg)

    @app.get("/api/v1/drones")
    def drones(_u=Depends(auth("commander", "operator", "admin"))):
        return list(db.drones.find({}))

    @app.post("/api/v1/drones/{drone_id}/telemetry", status_code=202)
    async def post_telemetry(drone_id: str, body: Telemetry, _u=Depends(auth("operator", "admin"))):
        if not db.drones.find_one({"_id": drone_id}):
            raise HTTPException(404, "unknown drone")
        await ingest_telemetry(drone_id, body)
        return {"accepted": True}

    @app.post("/api/v1/ai/analyse")
    async def ai_analyse(body: AnalyseRequest, _u=Depends(auth("operator", "admin"))):
        return await analyse_frame(body.droneId, body.incidentId, body.frameBase64)

    @app.get("/api/v1/firefighters")
    def firefighters(_u=Depends(auth("commander", "operator", "admin"))):
        return list(db.firefighters.find({}))

    @app.post("/api/v1/firefighters/{ff_id}/location", status_code=202)
    async def ff_location(ff_id: str, body: Location, _u=Depends(auth("crew", "admin"))):
        if not db.firefighters.find_one({"_id": ff_id}):
            raise HTTPException(404, "unknown firefighter")
        now = time.time()
        db.firefighters.update_one({"_id": ff_id}, {"$set": {"location": dbmod.point(body.lat, body.lon), "updatedAt": now,
                                                              "incidentId": body.incidentId}})
        await hub.broadcast({"type": "location", "firefighterId": ff_id, "lat": body.lat, "lon": body.lon, "ts": now})
        return {"accepted": True}

    @app.post("/api/v1/messages", status_code=201)
    async def post_message(body: Message, u=Depends(auth())):
        if not db.incidents.find_one({"_id": body.incidentId}):
            raise HTTPException(404, "unknown incident")
        doc = {"incidentId": body.incidentId, "channel": body.channel, "text": body.text, "from": u["sub"],
               "role": u["role"], "ts": time.time()}
        db.messages.insert_one(dict(doc))
        await hub.broadcast({"type": "message", **doc})
        return {"delivered": True}

    @app.get("/api/v1/messages")
    def get_messages(incidentId: str, _u=Depends(auth())):
        return list(db.messages.find({"incidentId": incidentId}, {"_id": 0}).sort("ts", 1))

    @app.post("/api/v1/sim/start", status_code=202)
    async def sim_start(body: SimStart, _u=Depends(auth("operator", "admin"))):
        inc = db.incidents.find_one({"_id": body.incidentId})
        if not inc or not inc.get("droneId"):
            raise HTTPException(404, "incident has no dispatched drone")
        start_mission(inc["droneId"], body.incidentId, body.timeScale)
        return {"started": True, "droneId": inc["droneId"]}

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket, token: str = Query(default="")):
        claims = decode_token(token)
        if not claims:
            await ws.close(code=4401)
            return
        await ws.accept()
        hub.clients.append((ws, claims["role"]))
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            hub.clients = [c for c in hub.clients if c[0] is not ws]

    static = os.path.join(os.path.dirname(__file__), "static")
    app.mount("/", StaticFiles(directory=static, html=True), name="static")
    return app


app = create_app() if os.getenv("FIRESIGHT_NO_AUTOAPP") != "1" else None
