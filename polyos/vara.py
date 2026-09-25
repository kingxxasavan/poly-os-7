"""Ask Vara: the PolyOS assistant.

Simple requests ("open firefox", "volume 40", "turn wifi off", "lock") are handled right here
on the computer. Everything else goes to a chat model through any OpenAI-compatible API:
Ollama Cloud by default (with the person's own API key), or any provider set in Settings > Vara. The API key
lives in ~/.config/polyos/vara.json (mode 600) and is never sent back to the UI.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import threading
import urllib.error
import urllib.request
from pathlib import Path

from .core import ApiError

# Vara talks to Ollama Cloud by default; each person adds their own API key (Settings > Vara
# or first-run setup). Any OpenAI-compatible service works, including a local Ollama.
DEFAULT_CONFIG = {"endpoint": "https://ollama.com/v1", "model": "gpt-oss:120b", "apiKey": ""}
LOCAL_HOSTS = ("127.0.0.1", "localhost", "[::1]")
HISTORY_LIMIT = 24
SYSTEM_PROMPT = (
    "You are Vara, the assistant built into PolyOS, a desktop operating system based on Debian and "
    "inspired by PolyOS 7 by PIXAPoLY. Be friendly, clear and brief: a few sentences unless the user "
    "asks for detail. You can already do these on your own when asked plainly: open an app ('open "
    "firefox'), set volume or brightness ('volume 40'), turn Wi-Fi on or off, lock the screen and "
    "open Settings or Files. For anything about the computer itself, give steps that fit PolyOS: the "
    "Home Menu opens from the pinwheel logo in the dock, the launcher lists every app, Settings has "
    "Appearance, Wi-Fi, Sound, Display, Power and Vara pages, and Debian's apt installs software."
)


class VaraConfig:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()

    def load(self) -> dict:
        try:
            data = json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError):
            data = {}
        return {k: data.get(k, v) if isinstance(data.get(k, v), str) else v for k, v in DEFAULT_CONFIG.items()}

    def public(self) -> dict:
        cfg = self.load()
        return {"endpoint": cfg["endpoint"], "model": cfg["model"], "hasKey": bool(cfg["apiKey"]), "needsKey": needs_key(cfg)}

    def update(self, endpoint: str | None, model: str | None, api_key: str | None) -> dict:
        with self._lock:
            cfg = self.load()
            if endpoint is not None:
                if not re.match(r"^https?://[^\s]+$", endpoint.strip()):
                    raise ApiError("The endpoint must be an http:// or https:// address.")
                cfg["endpoint"] = endpoint.strip().rstrip("/")
            if model is not None:
                if not model.strip() or len(model) > 200:
                    raise ApiError("Enter a model name.")
                cfg["model"] = model.strip()
            if api_key is not None:
                cfg["apiKey"] = api_key.strip()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(cfg, fh, indent=2)
        return self.public()


def needs_key(cfg: dict) -> bool:
    return not cfg.get("apiKey") and not any(h in cfg["endpoint"] for h in LOCAL_HOSTS)


def complete(cfg: dict, messages: list[dict], timeout: float = 90) -> str:
    """One chat completion from an OpenAI-compatible endpoint."""
    if needs_key(cfg):
        raise RuntimeError("Vara needs an API key to chat. Add yours in Settings > Vara (Ollama Cloud keys are free "
                           "at ollama.com). Simple requests like “open firefox” work without one.")
    body = json.dumps({"model": cfg["model"], "messages": messages, "stream": False}).encode()
    headers = {"Content-Type": "application/json"}
    if cfg.get("apiKey"):
        headers["Authorization"] = f"Bearer {cfg['apiKey']}"
    request = urllib.request.Request(f"{cfg['endpoint'].rstrip('/')}/chat/completions", data=body,
                                     headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = json.loads(exc.read()).get("error", "")
            detail = detail.get("message", "") if isinstance(detail, dict) else str(detail)
        except (ValueError, AttributeError):
            pass
        if exc.code in (401, 403):
            raise RuntimeError("The AI service rejected the API key. Check it in Settings > Vara.") from None
        if exc.code == 404:
            raise RuntimeError(f"The model “{cfg['model']}” wasn't found. {detail}".strip()) from None
        raise RuntimeError(f"The AI service returned an error ({exc.code}). {detail}".strip()) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise RuntimeError(
            f"Vara couldn't reach {cfg['endpoint']}. Check your internet connection, or change the provider "
            "in Settings > Vara. Simple requests like “open firefox” still work."
        ) from None
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, AttributeError):
        raise RuntimeError("The AI service sent back an answer Vara couldn't read.") from None


# ---- things Vara does directly -----------------------------------------------------------

_OPEN = re.compile(r"^(?:please\s+)?(?:open|launch|start|run)\s+(?:the\s+|my\s+)?(.+?)(?:\s+app)?[.!]*$", re.I)
_LEVEL = re.compile(r"^(?:set\s+(?:the\s+)?)?(volume|brightness)\s+(?:to\s+)?(\d{1,3})\s*%?[.!]*$", re.I)
_MUTE = re.compile(r"^(mute|unmute)(?:\s+(?:the\s+)?(?:sound|volume|audio))?[.!]*$", re.I)
_WIFI = re.compile(r"^(?:turn|switch)\s+(?:the\s+)?wi-?fi\s+(on|off)[.!]*$|^(?:turn|switch)\s+(on|off)\s+(?:the\s+)?wi-?fi[.!]*$", re.I)
_LOCK = re.compile(r"^lock(?:\s+(?:the\s+)?(?:screen|computer|pc))?[.!]*$", re.I)
_TIME = re.compile(r"^what(?:'s| is)\s+the\s+(time|date)(?:\s+(?:today|now))?\??$", re.I)


def match_app(apps: list[dict], name: str) -> dict | None:
    q = name.strip().lower()
    for test in (lambda a: a["name"].lower() == q, lambda a: a["name"].lower().startswith(q),
                 lambda a: q in a["name"].lower(), lambda a: q in a["id"].lower(),
                 lambda a: any(q == k.lower() for k in a.get("keywords", []))):
        found = next((a for a in apps if test(a)), None)
        if found:
            return found
    return None


def local_intent(backend, text: str) -> str | None:
    """Handle a request on the computer; None means 'ask the model'."""
    text = text.strip()
    if m := _LEVEL.match(text):
        what, level = m.group(1).lower(), max(0, min(100, int(m.group(2))))
        (backend.set_volume if what == "volume" else backend.set_brightness)(level=level)
        return f"Done: {what} is at {level}%."
    if m := _MUTE.match(text):
        backend.set_volume(muted=m.group(1).lower() == "mute")
        return "Muted." if m.group(1).lower() == "mute" else "Sound is back on."
    if m := _WIFI.match(text):
        on = (m.group(1) or m.group(2)).lower() == "on"
        backend.wifi_enable(on)
        return f"Wi-Fi is {'on' if on else 'off'}."
    if _LOCK.match(text):
        backend.power("lock")
        return "Locking the screen."
    if m := _TIME.match(text):
        now = datetime.datetime.now()
        if m.group(1).lower() == "date":
            return f"It's {now:%A}, {now:%B} {now.day}."
        return f"It's {now.hour % 12 or 12}:{now:%M} {'AM' if now.hour < 12 else 'PM'}."
    if m := _OPEN.match(text):
        target = m.group(1).strip().lower()
        if target in ("settings", "system settings"):
            backend.open_app("settings")
            return "Opening Settings."
        if target in ("files", "file manager", "my files", "file explorer"):
            backend.open_app("files")
            return "Opening Files."
        app = match_app(backend.apps(), target)
        if app:
            backend.launch(app["id"])
            return f"Opening {app['name']}."
        return None  # not an app: let the model answer ("open a can of soup")
    return None


class Vara:
    def __init__(self, config_path: Path):
        self.config = VaraConfig(config_path)
        self.history: list[dict] = []
        self._lock = threading.Lock()

    def reset(self) -> dict:
        with self._lock:
            self.history = []
        return {"history": []}

    def chat(self, backend, message: str) -> dict:
        message = message.strip()
        if not message:
            raise ApiError("Ask Vara something.")
        with self._lock:
            self.history.append({"role": "user", "content": message})
        try:
            reply = local_intent(backend, message)
            if reply is None:
                with self._lock:  # only role/content, and not Vara's own error notes
                    past = [{"role": m["role"], "content": m["content"]} for m in self.history[-HISTORY_LIMIT:]
                            if not m.get("error")]
                convo = [{"role": "system", "content": SYSTEM_PROMPT}, *past]
                reply = complete(self.config.load(), convo)
        except (RuntimeError, ApiError) as exc:
            reply, failed = str(exc), True
        else:
            failed = False
        with self._lock:
            self.history.append({"role": "assistant", "content": reply, **({"error": True} if failed else {})})
            self.history = self.history[-HISTORY_LIMIT:]
            return {"reply": reply, "error": failed, "history": list(self.history)}
