"""Pydantic request models. Invalid input is rejected with HTTP 422 before business logic runs."""
from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=6, max_length=100)


class CadAlert(BaseModel):
    callId: str = Field(min_length=3, max_length=40)
    priority: int = Field(ge=1, le=3)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    description: str = Field(default="", max_length=300)


class Telemetry(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    altitude: float = Field(ge=0, le=500)
    battery: float = Field(ge=0, le=100)
    heading: float = Field(ge=0, lt=360)
    incidentId: str | None = None


class AnalyseRequest(BaseModel):
    droneId: str = Field(min_length=2, max_length=20)
    incidentId: str = Field(min_length=3, max_length=20)
    frameBase64: str = Field(min_length=20, max_length=200_000)
    timestamp: float


class Location(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    incidentId: str | None = None


class Message(BaseModel):
    incidentId: str = Field(min_length=3, max_length=20)
    channel: str = Field(default="command", pattern="^(command|air|ground)$")
    text: str = Field(min_length=1, max_length=500)


class SimStart(BaseModel):
    incidentId: str
    timeScale: float = Field(default=10.0, gt=0, le=60)
