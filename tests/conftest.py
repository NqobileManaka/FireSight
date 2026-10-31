import os

os.environ["FIRESIGHT_NO_AUTOAPP"] = "1"
os.environ.setdefault("SIM_WIND_KMH", "18")

import mongomock
import pytest
from fastapi.testclient import TestClient

from app.main import create_app


def fresh_db():
    return mongomock.MongoClient()["firesight"]


def login(client, user="operator1", pw="firesight123"):
    r = client.post("/api/v1/auth/login", json={"username": user, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}, r.json()["token"]


@pytest.fixture()
def client():
    with TestClient(create_app(db=fresh_db(), sim_autostart=False)) as c:
        yield c


@pytest.fixture()
def sim_client():
    with TestClient(create_app(db=fresh_db(), sim_autostart=True)) as c:
        yield c
