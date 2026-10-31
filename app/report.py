"""Post-incident report generation (FR-09)."""
import time
import uuid


def build_report(db, incident: dict) -> dict:
    t0 = time.perf_counter()
    inc_id = incident["_id"]
    frames = list(db.telemetry.find({"incidentId": inc_id, "kind": "thermal"}).sort("ts", 1))
    timeline = []
    for f in frames:
        ai = f["aiResult"]
        timeline.append({"ts": f["ts"], "classification": ai["classification"], "severity": ai["severity"],
                         "hotspots": len(ai["hotspots"]), "areaM2": round(sum(h["areaM2"] for h in ai["hotspots"]), 1)})
    step = max(1, len(timeline) // 200)
    keep = None
    if frames:
        worst = max(frames, key=lambda f: (f["aiResult"]["severity"], f["ts"]))
        keep = {"ts": worst["ts"], "frameBase64": worst["frameBase64"], "aiResult": worst["aiResult"]}
    closed = incident.get("closedAt") or time.time()
    report = {
        "_id": f"RPT-{uuid.uuid4().hex[:8].upper()}", "incidentId": inc_id, "generatedAt": time.time(),
        "summary": {
            "callId": incident["callId"], "priority": incident["priority"], "droneId": incident.get("droneId"),
            "reportedAt": incident["reportedAt"], "dispatchSeconds": incident.get("dispatchSeconds"),
            "durationSeconds": round(closed - incident["reportedAt"], 2),
            "framesAnalysed": len(frames),
            "maxSeverity": max((t["severity"] for t in timeline), default=0),
            "peakHotspots": max((t["hotspots"] for t in timeline), default=0),
            "messages": db.messages.count_documents({"incidentId": inc_id}),
        },
        "hotspotTimeline": timeline[::step],
        "worstFrame": keep,
    }
    report["generationMs"] = round((time.perf_counter() - t0) * 1000, 2)
    db.reports.replace_one({"incidentId": inc_id}, report, upsert=True)
    return report
