"""Recovery keys: reset a forgotten password yourself, from the login or lock screen.

When an account is created, PolyOS shows a recovery key once (25 characters, 125 random
bits, like XXXXX-XXXXX-XXXXX-XXXXX-XXXXX). Only an scrypt hash of it is stored, in
/var/lib/polyos/recovery/<user> (root only). polyos-recover (this module's main, run as root
through pkexec) takes {"user", "key", "password"} as JSON on stdin and sets the new password
if the key matches. Wrong keys are slowed down and locked out after a few tries.

polkit allows pkexec of polyos-recover for the login screen (the lightdm user) and for
active local sessions without a password: the recovery key itself is the proof.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path

STORE = Path("/var/lib/polyos/recovery")
ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32: no I, L, O or U
KEY_CHARS = 25
MAX_FAILS = 5
LOCKOUT = 15 * 60
SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}


def generate() -> str:
    raw = "".join(secrets.choice(ALPHABET) for _ in range(KEY_CHARS))
    return "-".join(raw[i:i + 5] for i in range(0, KEY_CHARS, 5))


def normalize(key: str) -> str:
    """What people type: any case, spaces or dashes, and look-alike letters."""
    text = re.sub(r"[\s-]", "", key or "").upper()
    return text.translate(str.maketrans({"O": "0", "I": "1", "L": "1", "U": "V"}))


def looks_valid(key: str) -> bool:
    k = normalize(key)
    return len(k) == KEY_CHARS and all(c in ALPHABET for c in k)


def make_record(key: str) -> dict:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(normalize(key).encode(), salt=salt, dklen=32, **SCRYPT)
    return {"v": 1, "salt": salt.hex(), "hash": digest.hex(), **SCRYPT, "created": int(time.time())}


def check(record: dict, key: str) -> bool:
    try:
        digest = hashlib.scrypt(normalize(key).encode(), salt=bytes.fromhex(record["salt"]), dklen=32,
                                n=int(record["n"]), r=int(record["r"]), p=int(record["p"]))
    except (KeyError, ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), str(record.get("hash", "")))


def save_record(user: str, record: dict, root: Path = Path("/")) -> None:
    folder = root / STORE.relative_to("/")
    folder.mkdir(parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    path = folder / user
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(record, fh)
    (folder / f"{user}.fails").unlink(missing_ok=True)


def has_key(user: str) -> bool:
    try:
        return (STORE / user).is_file()
    except OSError:
        return False


class RecoveryError(Exception):
    pass


def _fails(user: str) -> list[float]:
    try:
        data = json.loads((STORE / f"{user}.fails").read_text())
        return [float(t) for t in data if time.time() - float(t) < LOCKOUT]
    except (OSError, ValueError, TypeError):
        return []


def recover(user: str, key: str, password: str) -> None:
    """Set `user`'s password if `key` is their recovery key (root only)."""
    import pwd

    if not re.match(r"^[a-z_][a-z0-9_-]{0,31}$", user or ""):
        raise RecoveryError("Unknown account.")
    try:
        entry = pwd.getpwnam(user)
    except KeyError:
        raise RecoveryError("Unknown account.") from None
    if entry.pw_uid < 1000 or entry.pw_uid >= 60000:
        raise RecoveryError("That account can't be reset here.")
    if not password or len(password) > 256 or "\n" in password or ":" in user:
        raise RecoveryError("Choose a new password.")
    try:
        record = json.loads((STORE / user).read_text())
    except (OSError, ValueError):
        raise RecoveryError("No recovery key was set up for this account. Ask someone with an administrator "
                            "account to reset your password in Settings > Account.") from None
    fails = _fails(user)
    if len(fails) >= MAX_FAILS:
        wait = int(LOCKOUT - (time.time() - min(fails))) // 60 + 1
        raise RecoveryError(f"Too many wrong recovery keys. Try again in {wait} minutes.")
    if not looks_valid(key) or not check(record, key):
        time.sleep(2)
        fails.append(time.time())
        (STORE / f"{user}.fails").write_text(json.dumps(fails))
        left = MAX_FAILS - len(fails)
        raise RecoveryError("That recovery key isn't right." + (f" {left} tries left." if left > 0 else ""))
    proc = subprocess.run(["chpasswd"], input=f"{user}:{password}\n", capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise RecoveryError("The password couldn't be changed: " + (proc.stderr.strip().splitlines() or ["unknown error"])[-1])
    (STORE / f"{user}.fails").unlink(missing_ok=True)


def main() -> int:
    """polyos-recover: JSON {"user", "key", "password"} on stdin; prints {"ok": true} or {"error": "..."}."""
    if os.geteuid() != 0:
        print(json.dumps({"error": "polyos-recover must run as root."}))
        return 1
    try:
        request = json.loads(sys.stdin.read(4096) or "{}")
        recover(str(request.get("user", "")), str(request.get("key", "")), str(request.get("password", "")))
    except RecoveryError as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    except (ValueError, subprocess.SubprocessError, OSError) as exc:
        print(json.dumps({"error": f"Password reset failed ({exc.__class__.__name__})."}))
        return 1
    print(json.dumps({"ok": True}))
    return 0


def run_helper(user: str, key: str, password: str) -> None:
    """Called from the login/lock screen: run polyos-recover through pkexec."""
    helper = "/usr/libexec/polyos/polyos-recover"
    try:
        proc = subprocess.run(["pkexec", helper], input=json.dumps({"user": user, "key": key, "password": password}),
                              capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        raise RecoveryError("pkexec is not installed, so passwords can't be reset here.") from None
    except subprocess.TimeoutExpired:
        raise RecoveryError("Resetting the password took too long.") from None
    try:
        result = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        result = {"error": (proc.stderr.strip().splitlines() or ["Password reset isn't available."])[-1]}
    if result.get("error"):
        raise RecoveryError(result["error"])


if __name__ == "__main__":
    sys.exit(main())
