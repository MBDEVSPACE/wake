"""Device list persistence.

The list lives in a single JSON file on a mounted volume so it survives
container updates. First boot can be seeded from the environment, which is how
someone who prefers editing compose to clicking buttons sets things up.
"""

import json
import os
import re
import threading
import uuid

from wol import normalize_mac

CONFIG_DIR = os.environ.get("WOL_CONFIG_DIR", "/config")
CONFIG_PATH = os.path.join(CONFIG_DIR, "devices.json")

_lock = threading.Lock()


def _blank():
    return {"devices": []}


def _read():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return _blank()
    if not isinstance(data, dict) or not isinstance(data.get("devices"), list):
        return _blank()
    return data


def _write(data):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    os.replace(tmp, CONFIG_PATH)


def clean(device, existing_id=None):
    """Validate and normalize one device, raising ValueError on bad input."""
    name = str(device.get("name") or "").strip()
    if not name:
        raise ValueError("Name is required")
    if len(name) > 64:
        raise ValueError("Name is too long")

    mac = normalize_mac(device.get("mac"))
    ip = str(device.get("ip") or "").strip()

    port = device.get("port")
    if port in ("", None):
        port = None
    else:
        try:
            port = int(port)
        except (TypeError, ValueError):
            raise ValueError("Port must be a number")
        if not 1 <= port <= 65535:
            raise ValueError("Port must be between 1 and 65535")

    broadcast = str(device.get("broadcast") or "").strip()

    return {
        "id": existing_id or uuid.uuid4().hex[:12],
        "name": name,
        "mac": mac,
        "ip": ip,
        "port": port,
        "broadcast": broadcast,
    }


def devices():
    with _lock:
        return list(_read()["devices"])


def get(device_id):
    for device in devices():
        if device["id"] == device_id:
            return device
    return None


def add(payload):
    device = clean(payload)
    with _lock:
        data = _read()
        data["devices"].append(device)
        _write(data)
    return device


def update(device_id, payload):
    device = clean(payload, existing_id=device_id)
    with _lock:
        data = _read()
        for index, existing in enumerate(data["devices"]):
            if existing["id"] == device_id:
                data["devices"][index] = device
                _write(data)
                return device
    return None


def remove(device_id):
    with _lock:
        data = _read()
        remaining = [d for d in data["devices"] if d["id"] != device_id]
        if len(remaining) == len(data["devices"]):
            return False
        data["devices"] = remaining
        _write(data)
        return True


def seed_from_env():
    """On first run only, import devices described by the environment."""
    if os.path.exists(CONFIG_PATH):
        return

    raw = os.environ.get("WOL_DEVICES", "").strip()
    incoming = []
    if raw:
        try:
            parsed = json.loads(raw)
            incoming = parsed if isinstance(parsed, list) else [parsed]
        except ValueError:
            # "Name=MAC@IP:PORT" entries, separated by commas or newlines.
            for chunk in re.split(r"[,\n]", raw):
                chunk = chunk.strip()
                if not chunk:
                    continue
                name, _, rest = chunk.partition("=")
                mac, _, host = rest.partition("@")
                ip, _, port = host.partition(":")
                incoming.append({"name": name, "mac": mac, "ip": ip, "port": port or None})
    elif os.environ.get("WOL_MAC"):
        incoming = [{
            "name": os.environ.get("WOL_NAME", "My PC"),
            "mac": os.environ["WOL_MAC"],
            "ip": os.environ.get("WOL_IP", ""),
            "port": os.environ.get("WOL_PORT") or None,
            "broadcast": os.environ.get("WOL_BROADCAST", ""),
        }]

    seeded = []
    for entry in incoming:
        try:
            seeded.append(clean(entry))
        except ValueError:
            continue
    _write({"devices": seeded})
