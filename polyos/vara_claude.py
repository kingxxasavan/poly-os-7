"""Vara's Claude provider: Anthropic's Messages API through Anthropic's official Python library.

Vara keeps its conversation in the OpenAI chat format, which its other providers speak. This
module turns that into a Messages API request and the reply back into the same shape, keeping
Claude's own content blocks (its reasoning included) with the reply, so they go back unchanged
on the next step of a tool loop.

Requests use adaptive thinking (shown in the chat as "Thinking") and server-side refusal
fallbacks ("default"): if a request is declined, Anthropic re-runs it on its recommended
fallback model in the same call.

Debian doesn't package the `anthropic` library, so the PolyOS image installs it into
/usr/lib/polyos/vendor (iso/config/hooks/live/0550-polyos-anthropic.hook.chroot). Elsewhere it is
fetched once into ~/.local/share/polyos/vendor the first time Claude is used.
"""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

DEFAULT_MODEL = "claude-opus-5"
ENDPOINT = "https://api.anthropic.com"
MAX_TOKENS = 16000
BETAS = ["server-side-fallback-2026-07-01"]  # the fallbacks="default" form
VENDOR_DIRS = (Path("/usr/lib/polyos/vendor"), Path.home() / ".local/share/polyos/vendor")


def sdk():
    """The anthropic module, from Python's own path, PolyOS's vendor folders, or fetched once."""
    try:
        return importlib.import_module("anthropic")
    except ImportError:
        pass
    for folder in VENDOR_DIRS:
        if folder.is_dir() and str(folder) not in sys.path:
            sys.path.append(str(folder))
    try:
        return importlib.import_module("anthropic")
    except ImportError:
        pass
    user_dir = VENDOR_DIRS[1]
    user_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
                           "--break-system-packages", "--target", str(user_dir), "anthropic"],
                          capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError("Vara couldn't set up Claude: Anthropic's library didn't download. Check your internet "
                           "connection and try again.")
    importlib.invalidate_caches()
    return importlib.import_module("anthropic")


# ---- the conversation, both ways (pure, so it's unit-tested without the library) -----------

def to_tools(openai_tools: list[dict]) -> list[dict]:
    return [{"name": t["function"]["name"], "description": t["function"]["description"],
             "input_schema": t["function"]["parameters"]} for t in openai_tools]


def to_messages(transcript: list[dict]) -> list[dict]:
    """Vara's transcript (OpenAI chat format) as Messages API messages. Tool results that follow
    one assistant turn go back together in a single user message."""
    out: list[dict] = []
    for m in transcript:
        role = m["role"]
        if role == "user":
            out.append({"role": "user", "content": m["content"]})
        elif role == "assistant":
            if m.get("_claude"):  # Claude's own blocks, exactly as they came
                out.append({"role": "assistant", "content": m["_claude"]})
                continue
            blocks = [{"type": "text", "text": m["content"]}] if m.get("content") else []
            for call in m.get("tool_calls") or []:
                try:
                    args = json.loads(call["function"].get("arguments") or "{}")
                except ValueError:
                    args = {}
                blocks.append({"type": "tool_use", "id": call["id"], "name": call["function"]["name"],
                               "input": args if isinstance(args, dict) else {}})
            if blocks:
                out.append({"role": "assistant", "content": blocks})
        elif role == "tool":
            result = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
            if m["content"].startswith("Error:"):
                result["is_error"] = True
            last = out[-1] if out else None
            if last and last["role"] == "user" and isinstance(last["content"], list) \
                    and all(b.get("type") == "tool_result" for b in last["content"]):
                last["content"].append(result)
            else:
                out.append({"role": "user", "content": [result]})
    return out


def from_blocks(blocks: list[dict]) -> dict:
    """Claude's reply content as Vara's reply message (with the raw blocks kept for replay)."""
    text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    thought = "\n\n".join(b["thinking"] for b in blocks if b.get("type") == "thinking" and b.get("thinking"))
    calls = [{"id": b["id"], "type": "function", "function": {"name": b["name"], "arguments": json.dumps(b.get("input") or {})}}
             for b in blocks if b.get("type") == "tool_use"]
    return {"role": "assistant", "content": text, "tool_calls": calls, "reasoning": thought, "_claude": blocks}


# ---- one request ----------------------------------------------------------------------------

def request(cfg: dict, system: str, transcript: list[dict], tools: list[dict] | None, timeout: float) -> dict:
    anthropic = sdk()
    base = cfg["endpoint"].rstrip("/")
    client = anthropic.Anthropic(api_key=cfg.get("apiKey") or None, base_url=base.removesuffix("/v1"),
                                 timeout=timeout, max_retries=2)
    params = {"model": cfg.get("model") or DEFAULT_MODEL, "max_tokens": MAX_TOKENS, "system": system,
              "messages": to_messages(transcript), "thinking": {"type": "adaptive", "display": "summarized"},
              "betas": BETAS, "fallbacks": "default"}
    if tools:
        params["tools"] = to_tools(tools)
    try:
        response = client.beta.messages.create(**params)
    except anthropic.AuthenticationError:
        raise RuntimeError("Claude rejected the API key. Check it in Settings > Vara.") from None
    except anthropic.PermissionDeniedError:
        raise RuntimeError("This API key can't use that Claude model. Check your Anthropic account.") from None
    except anthropic.NotFoundError:
        raise RuntimeError(f"The model “{params['model']}” wasn't found. Try {DEFAULT_MODEL}.") from None
    except anthropic.RateLimitError:
        raise RuntimeError("Claude is busy right now (rate limit). Wait a moment and try again.") from None
    except anthropic.BadRequestError as exc:
        raise RuntimeError(f"Claude couldn't take that request: {exc.message}") from None
    except anthropic.APIStatusError as exc:
        raise RuntimeError(f"Claude's service returned an error ({exc.status_code}). Try again in a moment.") from None
    except anthropic.APIConnectionError:
        raise RuntimeError("Vara couldn't reach Claude. Check your internet connection.") from None
    if response.stop_reason == "refusal":
        details = getattr(response, "stop_details", None)
        why = getattr(details, "explanation", None) if details else None
        raise RuntimeError(f"Claude declined this request.{f' {why}' if why else ''}")
    return from_blocks(response.to_dict()["content"])
