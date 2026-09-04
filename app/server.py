#!/usr/bin/env python3
"""Wake-on-LAN for ZimaOS.

A dependency-free HTTP service: static mobile-first UI plus a small JSON API
that sends magic packets and reports whether the target answered.
"""

import hmac
import json
import logging
import mimetypes
import os
import posixpath
import socket
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import status
import store
import wol

WEB_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
HOST = os.environ.get("WOL_HOST", "0.0.0.0")
PORT = int(os.environ.get("WOL_WEB_PORT", "8055"))
PIN = os.environ.get("WOL_PIN", "").strip()
MAX_BODY = 64 * 1024

log = logging.getLogger("wol")


class Handler(BaseHTTPRequestHandler):
    server_version = "zima-wol"
    protocol_version = "HTTP/1.1"

    # -- plumbing ---------------------------------------------------------

    def log_message(self, fmt, *args):
        log.info("%s %s", self.address_string(), fmt % args)

    def _send(self, code, body=b"", content_type="text/plain; charset=utf-8", headers=None):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code, payload):
        self._send(code, json.dumps(payload).encode(), "application/json; charset=utf-8")

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_BODY:
            raise ValueError("Request body is too large")
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except ValueError:
            raise ValueError("Request body is not valid JSON")

    def _authorized(self):
        if not PIN:
            return True
        supplied = self.headers.get("X-Wol-Pin", "")
        return hmac.compare_digest(supplied, PIN)

    # -- routing ----------------------------------------------------------

    def do_GET(self):
        self._route("GET")

    def do_HEAD(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")

    def do_PUT(self):
        self._route("PUT")

    def do_DELETE(self):
        self._route("DELETE")

    def _route(self, method):
        path = urlparse(self.path).path.rstrip("/") or "/"

        try:
            if path == "/healthz":
                return self._json(200, {"status": "ok"})
            if path == "/api/session":
                return self._session(method)
            if path.startswith("/api/"):
                if not self._authorized():
                    return self._json(401, {"error": "PIN required"})
                return self._api(method, path)
            if method == "GET":
                return self._static(path)
            return self._json(405, {"error": "Method not allowed"})
        except ValueError as exc:
            return self._json(400, {"error": str(exc)})
        except Exception:  # noqa: BLE001 - never leak a traceback to the LAN
            log.exception("unhandled error on %s %s", method, path)
            return self._json(500, {"error": "Internal server error"})

    def _session(self, method):
        """Unauthenticated: lets the UI learn whether it must ask for a PIN."""
        if method == "GET":
            return self._json(200, {"pin_required": bool(PIN), "authorized": self._authorized()})
        if method == "POST":
            body = self._body()
            ok = not PIN or hmac.compare_digest(str(body.get("pin", "")), PIN)
            return self._json(200 if ok else 401, {"authorized": ok})
        return self._json(405, {"error": "Method not allowed"})

    def _api(self, method, path):
        parts = path.strip("/").split("/")[1:]  # drop "api"

        if parts == ["devices"]:
            if method == "GET":
                return self._json(200, {"devices": store.devices()})
            if method == "POST":
                return self._json(201, store.add(self._body()))
            return self._json(405, {"error": "Method not allowed"})

        if parts == ["status"]:
            if method != "GET":
                return self._json(405, {"error": "Method not allowed"})
            devices = store.devices()
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(status.check, devices))
            return self._json(200, {
                "statuses": {d["id"]: r for d, r in zip(devices, results)},
            })

        if len(parts) >= 2 and parts[0] == "devices":
            device_id = parts[1]
            action = parts[2] if len(parts) > 2 else None

            if action == "wake" and method == "POST":
                return self._wake(device_id)
            if action:
                return self._json(404, {"error": "Not found"})
            if method == "PUT":
                updated = store.update(device_id, self._body())
                if not updated:
                    return self._json(404, {"error": "Device not found"})
                return self._json(200, updated)
            if method == "DELETE":
                if not store.remove(device_id):
                    return self._json(404, {"error": "Device not found"})
                return self._json(200, {"deleted": device_id})
            return self._json(405, {"error": "Method not allowed"})

        return self._json(404, {"error": "Not found"})

    def _wake(self, device_id):
        device = store.get(device_id)
        if not device:
            return self._json(404, {"error": "Device not found"})
        try:
            targets = wol.wake(device["mac"], device.get("broadcast"), device.get("ip"))
        except OSError as exc:
            log.error("wake failed for %s: %s", device["name"], exc)
            return self._json(502, {"error": "Could not send the magic packet: %s" % exc})
        log.info("magic packet sent to %s (%s) via %s", device["name"], device["mac"], ", ".join(targets))
        return self._json(200, {"sent": True, "mac": device["mac"], "targets": targets})

    def _static(self, path):
        if path == "/":
            path = "/index.html"
        relative = posixpath.normpath(path).lstrip("/")
        full = os.path.join(WEB_ROOT, relative)
        if not os.path.abspath(full).startswith(WEB_ROOT + os.sep) or not os.path.isfile(full):
            return self._send(404, b"Not found")
        with open(full, "rb") as handle:
            body = handle.read()
        content_type = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if content_type.startswith(("text/", "application/javascript", "application/json")):
            content_type += "; charset=utf-8"
        return self._send(200, body, content_type, {"Cache-Control": "no-cache"})


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    address_family = socket.AF_INET


def main():
    logging.basicConfig(
        level=os.environ.get("WOL_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    store.seed_from_env()
    log.info("broadcast addresses: %s", ", ".join(wol.broadcast_addresses()) or "none detected")
    log.info("PIN protection %s", "enabled" if PIN else "disabled")
    log.info("listening on http://%s:%d", HOST, PORT)
    Server((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
