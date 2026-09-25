"""Widgets board data: weather, news, to-do, notes, photos, world clocks and media.

Weather comes from Open-Meteo (free, no API key) for the city the person picks; news from
BBC News RSS feeds. Both are fetched by the backend (the UI may only talk to PolyOS) and
cached. To-dos, notes and widget settings live in ~/.config/polyos/widgets.json.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from .core import IMAGE_TYPES, WIDGET_IDS, ApiError

ALL_WIDGETS = WIDGET_IDS
USER_AGENT = "PolyOS/0.2 (+https://github.com/kingxxasavan/poly-os-7-debain-receration)"
NEWS_FEEDS = {
    "top": ("Top stories", "https://feeds.bbci.co.uk/news/rss.xml"),
    "world": ("World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    "us": ("US & Canada", "https://feeds.bbci.co.uk/news/world/us_and_canada/rss.xml"),
    "technology": ("Technology", "https://feeds.bbci.co.uk/news/technology/rss.xml"),
    "science": ("Science", "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml"),
    "business": ("Business", "https://feeds.bbci.co.uk/news/business/rss.xml"),
    "entertainment": ("Entertainment", "https://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml"),
    "sport": ("Sport", "https://feeds.bbci.co.uk/sport/rss.xml"),
}
DEFAULT_DATA = {
    "weather": {"place": None, "units": "fahrenheit"},
    "news": {"topic": "top"},
    "clocks": ["Europe/London", "Asia/Tokyo"],
    "todo": [],
    "notes": "",
}
WEATHER_TTL = 10 * 60
NEWS_TTL = 15 * 60


def _fetch(url: str, timeout: float = 8) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read(2 * 1024 * 1024)
    except OSError as exc:
        raise ApiError("Couldn't reach the internet. Check your connection.", 503) from exc


def parse_rss(data: bytes, limit: int = 10) -> list[dict]:
    root = ET.fromstring(data)
    items = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not title or not link.startswith(("https://", "http://")):
            continue
        items.append({"title": title, "link": link, "summary": (item.findtext("description") or "").strip()[:240],
                      "published": (item.findtext("pubDate") or "").strip()})
        if len(items) >= limit:
            break
    return items


def _place(value) -> dict | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ApiError("weather place must be an object")
    try:
        lat, lon = float(value["latitude"]), float(value["longitude"])
    except (KeyError, TypeError, ValueError):
        raise ApiError("weather place needs latitude and longitude") from None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ApiError("weather place is out of range")
    return {"name": str(value.get("name", ""))[:80], "region": str(value.get("region", ""))[:80],
            "country": str(value.get("country", ""))[:80], "latitude": lat, "longitude": lon}


class Widgets:
    def __init__(self, path: Path, home: Path):
        self.path = path
        self.home = home
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[float, object]] = {}

    # ---- stored data ------------------------------------------------------------------
    def data(self) -> dict:
        try:
            raw = json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError):
            raw = {}
        out = json.loads(json.dumps(DEFAULT_DATA))
        if isinstance(raw, dict):
            for key, default in out.items():
                value = raw.get(key)
                if isinstance(default, dict) and isinstance(value, dict):
                    out[key] = {**default, **value}
                elif value is not None and isinstance(value, type(default)):
                    out[key] = value
        return out

    def update(self, patch: dict) -> dict:
        if not isinstance(patch, dict) or not patch:
            raise ApiError("expected an object")
        with self._lock:
            data = self.data()
            for key, value in patch.items():
                if key == "todo":
                    if not isinstance(value, list) or len(value) > 100:
                        raise ApiError("todo must be a list of up to 100 items")
                    data["todo"] = [{"text": str(t.get("text", ""))[:200], "done": bool(t.get("done"))}
                                    for t in value if isinstance(t, dict) and str(t.get("text", "")).strip()]
                elif key == "notes":
                    if not isinstance(value, str) or len(value) > 20000:
                        raise ApiError("notes must be text (up to 20,000 characters)")
                    data["notes"] = value
                elif key == "clocks":
                    if not isinstance(value, list) or len(value) > 4 or not all(
                            isinstance(z, str) and re.match(r"^[A-Za-z0-9_+/-]{1,64}$", z) for z in value):
                        raise ApiError("clocks must be up to 4 time zones")
                    data["clocks"] = value
                elif key == "weather":
                    if not isinstance(value, dict):
                        raise ApiError("weather must be an object")
                    if "place" in value:
                        data["weather"]["place"] = _place(value["place"])
                        self._cache.pop("weather", None)
                    if "units" in value:
                        if value["units"] not in ("fahrenheit", "celsius"):
                            raise ApiError("units must be fahrenheit or celsius")
                        data["weather"]["units"] = value["units"]
                        self._cache.pop("weather", None)
                elif key == "news":
                    topic = (value or {}).get("topic") if isinstance(value, dict) else None
                    if topic not in NEWS_FEEDS:
                        raise ApiError("unknown news topic")
                    data["news"]["topic"] = topic
                else:
                    raise ApiError(f"unknown widget setting: {key}")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2) + "\n", "utf-8")
            os.replace(tmp, self.path)
            return data

    def _cached(self, key: str, ttl: float, make):
        hit = self._cache.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        value = make()
        self._cache[key] = (time.time(), value)
        return value

    # ---- internet ---------------------------------------------------------------------
    def geocode(self, query: str) -> list[dict]:
        query = (query or "").strip()
        if len(query) < 2:
            return []
        url = "https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode(
            {"name": query[:80], "count": 8, "language": "en", "format": "json"})
        results = json.loads(_fetch(url)).get("results") or []
        return [{"name": r.get("name", ""), "region": r.get("admin1", ""), "country": r.get("country", ""),
                 "latitude": r.get("latitude"), "longitude": r.get("longitude")} for r in results]

    def weather(self) -> dict:
        settings = self.data()["weather"]
        place = settings.get("place")
        if not place:
            return {"place": None}

        def make():
            params = {
                "latitude": place["latitude"], "longitude": place["longitude"], "timezone": "auto", "forecast_days": 5,
                "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,is_day,wind_speed_10m",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "temperature_unit": settings["units"], "wind_speed_unit": "mph" if settings["units"] == "fahrenheit" else "kmh",
            }
            data = json.loads(_fetch("https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params)))
            cur, daily = data.get("current") or {}, data.get("daily") or {}
            days = [{"date": d, "code": c, "high": hi, "low": lo, "rain": r} for d, c, hi, lo, r in zip(
                daily.get("time", []), daily.get("weather_code", []), daily.get("temperature_2m_max", []),
                daily.get("temperature_2m_min", []), daily.get("precipitation_probability_max", []))]
            return {"place": place, "units": settings["units"], "temp": cur.get("temperature_2m"),
                    "feels": cur.get("apparent_temperature"), "humidity": cur.get("relative_humidity_2m"),
                    "wind": cur.get("wind_speed_10m"), "code": cur.get("weather_code"), "day": bool(cur.get("is_day", 1)),
                    "days": days, "updated": int(time.time())}

        return self._cached("weather", WEATHER_TTL, make)

    def news(self, topic: str | None = None) -> dict:
        topic = topic if topic in NEWS_FEEDS else self.data()["news"]["topic"]
        label, url = NEWS_FEEDS[topic]
        try:
            items = self._cached(f"news:{topic}", NEWS_TTL, lambda: parse_rss(_fetch(url)))
        except ET.ParseError:
            raise ApiError("The news feed couldn't be read right now.", 502) from None
        return {"topic": topic, "label": label, "source": "BBC News", "items": items,
                "topics": [[k, v[0]] for k, v in NEWS_FEEDS.items()]}

    # ---- this computer ------------------------------------------------------------------
    def photos(self, limit: int = 40) -> list[str]:
        base = self.home / "Pictures"
        found: list[str] = []
        if not base.is_dir():
            return found
        for folder, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if not d.startswith(".")][:20]
            if len(Path(folder).relative_to(base).parts) >= 2:
                dirs[:] = []
            for name in sorted(files):
                if Path(name).suffix.lower() in IMAGE_TYPES and Path(name).suffix.lower() != ".svg":
                    found.append(str(Path(folder) / name))
                    if len(found) >= limit:
                        return found
        return found

    def media(self) -> dict:
        if not shutil.which("playerctl"):
            return {"available": False}
        try:
            out = subprocess.run(["playerctl", "metadata", "--format",
                                  "{{status}}\t{{artist}}\t{{title}}\t{{playerName}}"],
                                 capture_output=True, text=True, timeout=3).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return {"available": True, "playing": None}
        if not out:
            return {"available": True, "playing": None}
        status, artist, title, player = (out.split("\t") + ["", "", "", ""])[:4]
        return {"available": True, "playing": {"status": status, "artist": artist, "title": title, "player": player}}

    def media_action(self, action: str) -> dict:
        if action not in ("play-pause", "next", "previous"):
            raise ApiError("unknown media action")
        if shutil.which("playerctl"):
            subprocess.run(["playerctl", action], capture_output=True, timeout=3)
        return self.media()
