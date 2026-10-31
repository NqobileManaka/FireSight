"""Hardware Abstraction Layer (HAL): every drone backend implements DroneAdapter.

The platform only talks to this interface, so the simulator can be replaced by a real
vendor SDK adapter without changing the dispatch, AI, GIS or reporting modules (FR-10).
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np


@dataclass
class DroneSample:
    lat: float
    lon: float
    altitude: float
    battery: float
    heading: float


class DroneAdapter(ABC):
    drone_id: str

    @abstractmethod
    def goto(self, lat: float, lon: float, altitude: float) -> None: ...

    @abstractmethod
    def step(self, dt: float) -> DroneSample:
        """Advance (simulated) time by dt seconds and return the current telemetry sample."""

    @abstractmethod
    def arrived(self) -> bool: ...

    @abstractmethod
    def thermal_frame(self) -> np.ndarray | None:
        """Return a 64x64 float32 thermal frame or None when the camera has nothing to send."""

    @abstractmethod
    def return_home(self) -> None: ...


class DJIAdapter(DroneAdapter):  # pragma: no cover - documented extension point, not implemented
    """Placeholder for the DJI Cloud / Matrice 350 RTK adapter (requires physical hardware and SDK keys)."""

    def __init__(self, *_a, **_k):
        raise NotImplementedError("DJI adapter is out of scope for the prototype (no hardware available)")

    goto = step = arrived = thermal_frame = return_home = lambda self, *a, **k: None
