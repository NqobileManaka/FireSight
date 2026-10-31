"""Simulated drone + fire scenario engine (HAL simulation adapter)."""
import math

import numpy as np

from app.ai import synth
from app.geo import haversine_m, latlon_to_pixel, offset_latlon
from app.hal.base import DroneAdapter, DroneSample

CRUISE_MS = 18.0        # metres per second
DRAIN_PER_S = 0.06      # battery % per second of flight


class FireScenario:
    """Ground-truth fire: a growing cluster of hotspots around (lat, lon)."""

    def __init__(self, lat, lon, seed=0, growth=0.05, critical_after_s=None):
        self.lat, self.lon, self.t = lat, lon, 0.0
        self.rng = np.random.default_rng(seed)
        self.growth = growth
        self.offsets = [(0.0, 0.0), (7.0, -4.0), (-6.0, 5.0)]     # metres east/north of the centre
        self.critical_after_s = critical_after_s

    def radius_m(self):
        return 3.0 + self.growth * self.t * 6

    def truth_points(self):
        return [offset_latlon(self.lat, self.lon, e, n) for e, n in self.offsets]

    def advance(self, dt):
        self.t += dt

    def frame_for(self, drone_lat, drone_lon, altitude, mpp):
        spots = []
        big = self.critical_after_s is not None and self.t >= self.critical_after_s
        for (la, lo) in self.truth_points():
            x, y = latlon_to_pixel(la, lo, drone_lat, drone_lon, altitude)
            sigma_m = self.radius_m() * (2.6 if big else 0.6)
            spots.append((x, y, max(1.6, sigma_m / mpp), 0.9))
        return synth.render(spots, self.rng)


class SimulatedDrone(DroneAdapter):
    def __init__(self, drone_id, lat, lon, battery=100.0):
        self.drone_id = drone_id
        self.lat, self.lon, self.alt, self.battery, self.heading = lat, lon, 0.0, battery, 0.0
        self.home = (lat, lon)
        self.target = None
        self.scenario: FireScenario | None = None

    def goto(self, lat, lon, altitude):
        self.target = (lat, lon, altitude)

    def return_home(self):
        self.target = (*self.home, 0.0)

    def arrived(self):
        if not self.target:
            return True
        return haversine_m(self.lat, self.lon, *self.target[:2]) < 3.0 and abs(self.alt - self.target[2]) < 1.0

    def step(self, dt, real_dt=None):
        """dt = simulated seconds for motion; real_dt = wall-clock seconds used to grow the fire once on scene."""
        if self.target:
            tlat, tlon, talt = self.target
            dist = haversine_m(self.lat, self.lon, tlat, tlon)
            if dist > 3.0:
                frac = min(1.0, CRUISE_MS * dt / dist)
                self.heading = (math.degrees(math.atan2((tlon - self.lon) * math.cos(math.radians(self.lat)),
                                                        tlat - self.lat)) + 360) % 360
                self.lat += (tlat - self.lat) * frac
                self.lon += (tlon - self.lon) * frac
            self.alt += max(-6 * dt, min(6 * dt, talt - self.alt))
            self.battery = max(0.0, self.battery - DRAIN_PER_S * dt)
        if self.scenario and self.arrived():
            self.scenario.advance(dt if real_dt is None else real_dt)
        return DroneSample(self.lat, self.lon, self.alt, self.battery, self.heading % 360)

    def thermal_frame(self):
        if not self.scenario or self.alt < 20:
            return None
        from app.geo import metres_per_pixel
        return self.scenario.frame_for(self.lat, self.lon, self.alt, metres_per_pixel(self.alt))
