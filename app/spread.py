"""Heuristic fire-spread prediction (wind-driven ellipse). Not a validated fire-behaviour model."""
import math
import os

from app.geo import offset_latlon


def get_weather(lat: float, lon: float) -> dict:
    """OpenWeatherMap when OPENWEATHER_KEY is set, otherwise a fixed simulated wind (documented limitation)."""
    key = os.getenv("OPENWEATHER_KEY")
    if key:
        import httpx
        r = httpx.get("https://api.openweathermap.org/data/2.5/weather",
                      params={"lat": lat, "lon": lon, "appid": key, "units": "metric"}, timeout=5)
        d = r.json()
        return {"windKmh": d["wind"]["speed"] * 3.6, "windFromDeg": d["wind"].get("deg", 0), "source": "openweathermap"}
    return {"windKmh": float(os.getenv("SIM_WIND_KMH", 18)), "windFromDeg": float(os.getenv("SIM_WIND_FROM", 270)),
            "source": "simulated"}


def predict(centre_lat, centre_lon, burning_area_m2, weather, horizon_min=15, slope_deg=0.0) -> dict:
    r0 = max(8.0, math.sqrt(max(burning_area_m2, 1.0) / math.pi))
    wind = weather["windKmh"]
    forward = r0 + horizon_min * (1.5 + 0.35 * wind) * (1 + math.tan(math.radians(slope_deg)))
    back = r0 + horizon_min * 0.25
    side = r0 + horizon_min * (0.6 + 0.05 * wind)
    to_deg = (weather["windFromDeg"] + 180) % 360           # fire spreads downwind
    t = math.radians(to_deg)
    pts = []
    for k in range(0, 36):
        a = 2 * math.pi * k / 36
        along = forward * math.cos(a) if math.cos(a) >= 0 else back * math.cos(a)
        across = side * math.sin(a)
        east = along * math.sin(t) + across * math.cos(t)
        north = along * math.cos(t) - across * math.sin(t)
        lat, lon = offset_latlon(centre_lat, centre_lon, east, north)
        pts.append([lon, lat])
    pts.append(pts[0])
    return {"type": "Feature", "properties": {"horizonMin": horizon_min, "spreadTowardDeg": to_deg,
                                              "forwardM": round(forward, 1), "weather": weather},
            "geometry": {"type": "Polygon", "coordinates": [pts]}}
