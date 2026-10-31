"""MongoDB access. Uses MONGO_URI (MongoDB Atlas) when set, otherwise an in-memory mongomock store."""
import os

from app.security import hash_password

SEED_DRONES = [
    ("DR-01", "Pretoria CBD station", -25.7461, 28.1881),
    ("DR-02", "Centurion station", -25.8603, 28.1894),
    ("DR-03", "Soshanguve station", -25.5240, 28.0990),
]
SEED_USERS = [
    ("commander1", "commander"),
    ("operator1", "operator"),
    ("crew1", "crew"),
    ("admin1", "admin"),
]


def point(lat: float, lon: float) -> dict:
    return {"type": "Point", "coordinates": [lon, lat]}


def get_db():
    uri = os.getenv("MONGO_URI")
    if uri:
        from pymongo import MongoClient
        return MongoClient(uri)[os.getenv("MONGO_DB", "firesight")]
    import mongomock
    return mongomock.MongoClient()["firesight"]


def seed(db, demo_password: str = "firesight123") -> None:
    for drone_id, base, lat, lon in SEED_DRONES:
        db.drones.update_one(
            {"_id": drone_id},
            {"$setOnInsert": {"base": base, "status": "idle", "battery": 100.0, "altitude": 0.0,
                              "heading": 0.0, "location": point(lat, lon), "homeLocation": point(lat, lon)}},
            upsert=True)
    for username, role in SEED_USERS:
        db.users.update_one({"_id": username},
                            {"$setOnInsert": {"role": role, "passwordHash": hash_password(demo_password)}},
                            upsert=True)
    for i in range(1, 4):
        db.firefighters.update_one({"_id": f"FF-{i:02d}"},
                                   {"$setOnInsert": {"name": f"Crew member {i}", "badge": f"TSH-{1000 + i}",
                                                     "location": None, "updatedAt": None}}, upsert=True)
    try:  # geospatial + housekeeping indexes (Atlas). mongomock ignores unsupported options.
        db.drones.create_index([("location", "2dsphere")])
        db.incidents.create_index([("location", "2dsphere")])
        db.telemetry.create_index([("incidentId", 1), ("ts", 1)])
    except Exception:
        pass
