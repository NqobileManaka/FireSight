"""Geodesy helpers and the nadir-camera georeferencing model."""
import math

EARTH_R = 6_371_000.0
FRAME_PX = 64
CAMERA_FOV_DEG = 60.0


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(a))


def offset_latlon(lat, lon, east_m, north_m):
    dlat = math.degrees(north_m / EARTH_R)
    dlon = math.degrees(east_m / (EARTH_R * math.cos(math.radians(lat))))
    return lat + dlat, lon + dlon


def metres_per_pixel(altitude_m: float) -> float:
    return 2 * altitude_m * math.tan(math.radians(CAMERA_FOV_DEG / 2)) / FRAME_PX


def pixel_to_latlon(px: float, py: float, drone_lat, drone_lon, altitude_m, heading_deg=0.0):
    """Project a pixel of a downward-facing frame onto the ground (north-up when heading=0)."""
    mpp = metres_per_pixel(altitude_m)
    east = (px - FRAME_PX / 2) * mpp
    north = -(py - FRAME_PX / 2) * mpp
    h = math.radians(heading_deg)
    e = east * math.cos(h) + north * math.sin(h)
    n = -east * math.sin(h) + north * math.cos(h)
    return offset_latlon(drone_lat, drone_lon, e, n)


def latlon_to_pixel(lat, lon, drone_lat, drone_lon, altitude_m):
    mpp = metres_per_pixel(altitude_m)
    north = math.radians(lat - drone_lat) * EARTH_R
    east = math.radians(lon - drone_lon) * EARTH_R * math.cos(math.radians(drone_lat))
    return FRAME_PX / 2 + east / mpp, FRAME_PX / 2 - north / mpp
