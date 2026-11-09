"""HTTP relay that turns an authenticated POST into a Wake-on-LAN packet.

All deployment specifics (token, target MAC, broadcast address, ports) come
from environment variables at runtime. Nothing is hardcoded.
"""

from __future__ import annotations

import hmac
import ipaddress
import json
import logging
import math
import os
import threading
import time
from collections import deque
from dataclasses import dataclass

from flask import Flask, jsonify, request

import logging_setup
from wol import normalize_mac, send_magic_packet

LOG = logging.getLogger("wol-relay")

VERSION = "1.0.8"

AUTH_HEADER = "X-Auth-Token"

# A valid request is a few dozen bytes. Waitress (before the app runs) and
# Flask both refuse anything bigger with 413, so nothing large is buffered.
MAX_BODY_BYTES = 4096

# Wrong tokens per client address: this many in the window lock the address
# out until the oldest failure leaves the window.
THROTTLE_FAILURES = 20
THROTTLE_WINDOW_SECONDS = 15 * 60
THROTTLE_MAX_ADDRESSES = 4096


class ConfigError(RuntimeError):
    """Raised when the environment is missing or malformed."""


@dataclass(frozen=True)
class Config:
    auth_token: str
    default_mac: str | None
    broadcast_address: str
    wol_port: int
    listen_host: str
    listen_port: int
    log_level: str
    allow_body_mac: bool

    @classmethod
    def from_env(cls, env: "os._Environ[str] | dict[str, str] | None" = None) -> "Config":
        env = os.environ if env is None else env

        token = env.get("WOL_AUTH_TOKEN", "")
        if not token:
            raise ConfigError("WOL_AUTH_TOKEN is required and must not be empty")

        raw_mac = env.get("WOL_TARGET_MAC", "").strip()
        default_mac: str | None = None
        if raw_mac:
            try:
                default_mac = normalize_mac(raw_mac)
            except ValueError as exc:
                raise ConfigError(f"WOL_TARGET_MAC is not a MAC address: {exc}") from exc

        allow_body_mac = _bool_env(env, "WOL_ALLOW_BODY_MAC", default=True)
        if default_mac is None and not allow_body_mac:
            raise ConfigError(
                "no target reachable: set WOL_TARGET_MAC or enable WOL_ALLOW_BODY_MAC"
            )

        # Checked here: a typo would otherwise only show up as a 502 on the
        # first wake-up, or end the start in a traceback.
        broadcast = env.get("WOL_BROADCAST_ADDRESS", "").strip() or "255.255.255.255"
        try:
            ipaddress.IPv4Address(broadcast)
        except ValueError as exc:
            raise ConfigError(f"WOL_BROADCAST_ADDRESS must be an IPv4 address, got {broadcast!r}") from exc
        log_level = env.get("WOL_LOG_LEVEL", "").strip().upper() or "INFO"
        if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
            raise ConfigError(f"WOL_LOG_LEVEL must be DEBUG, INFO, WARNING or ERROR, got {log_level!r}")

        return cls(
            auth_token=token,
            default_mac=default_mac,
            broadcast_address=broadcast,
            wol_port=_int_env(env, "WOL_PORT", 9),
            listen_host=env.get("WOL_LISTEN_HOST", "0.0.0.0"),
            listen_port=_int_env(env, "WOL_LISTEN_PORT", 8099),
            log_level=log_level,
            allow_body_mac=allow_body_mac,
        )


def _int_env(env, name: str, default: int) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc
    if not 1 <= value <= 65535:
        raise ConfigError(f"{name} must be between 1 and 65535, got {value}")
    return value


def _bool_env(env, name: str, default: bool) -> bool:
    raw = env.get(name, "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name} must be a boolean, got {raw!r}")


class FailureThrottle:
    """In-memory count of failed token checks per client address.

    Held in memory only, so a restart clears it. The number of tracked
    addresses is capped, so a scanner can't grow it without bound.
    """

    def __init__(
        self,
        limit: int = THROTTLE_FAILURES,
        window: float = THROTTLE_WINDOW_SECONDS,
        max_addresses: int = THROTTLE_MAX_ADDRESSES,
        clock=time.monotonic,
    ) -> None:
        self._limit = limit
        self._window = window
        self._max_addresses = max_addresses
        self._clock = clock
        self._failures: dict[str, deque[float]] = {}
        self._announced: set[str] = set()
        self._lock = threading.Lock()

    def attempt(self, address: str) -> tuple[int, bool]:
        """Count an attempt before the token is checked.

        Returns ``(retry_after, first)``: ``retry_after`` is 0 when the
        attempt may go on, else the seconds until the address is free again;
        ``first`` is True for the first refusal in a window, so the caller
        logs the throttle once, not once per request.
        """
        now = self._clock()
        with self._lock:
            times = self._failures.get(address)
            if times is None:
                self._make_room(now)
                times = self._failures[address] = deque()
            while times and now - times[0] >= self._window:
                times.popleft()
            if not times:
                self._announced.discard(address)
            if len(times) >= self._limit:
                first = address not in self._announced
                self._announced.add(address)
                return max(1, math.ceil(times[0] + self._window - now)), first
            times.append(now)
            return 0, False

    def succeeded(self, address: str) -> None:
        """Take back the attempt counted for a request whose token was right."""
        with self._lock:
            times = self._failures.get(address)
            if times:
                times.pop()
            if not times:
                self._failures.pop(address, None)
                self._announced.discard(address)

    def _make_room(self, now: float) -> None:
        if len(self._failures) < self._max_addresses:
            return
        for address in [a for a, t in self._failures.items() if not t or now - t[-1] >= self._window]:
            del self._failures[address]
            self._announced.discard(address)
        while len(self._failures) >= self._max_addresses:
            oldest = next(iter(self._failures))
            del self._failures[oldest]
            self._announced.discard(oldest)


def create_app(config: Config | None = None) -> Flask:
    config = Config.from_env() if config is None else config

    app = Flask(__name__)
    app.config["WOL_RELAY"] = config
    app.config["MAX_CONTENT_LENGTH"] = MAX_BODY_BYTES

    @app.get("/health")
    def health():
        return jsonify(status="ok"), 200

    throttle = FailureThrottle()

    @app.errorhandler(413)
    def too_large(_error):
        return jsonify(error="request body too large"), 413

    @app.post("/wol")
    def wake():
        client = request.remote_addr or "unknown"
        retry_after, first = throttle.attempt(client)
        if retry_after:
            if first:
                LOG.warning("auth_throttled", extra={"client": client, "retry_after": retry_after})
            response = jsonify(error="too many failed attempts")
            response.headers["Retry-After"] = str(retry_after)
            return response, 429
        if not _authorized(config.auth_token):
            LOG.warning("auth_rejected", extra={"path": "/wol", "client": client})
            return jsonify(error="unauthorized"), 401
        throttle.succeeded(client)

        try:
            body = _read_body()
        except ValueError as exc:
            return jsonify(error=str(exc)), 400

        supplied = "mac" in body
        if supplied and not config.allow_body_mac:
            LOG.warning("body_mac_refused")
            return jsonify(error="per-request MAC override is disabled"), 400

        source = "body" if supplied else "env"
        if supplied:
            try:
                mac = normalize_mac(body["mac"])
            except ValueError:
                LOG.warning("invalid_mac", extra={"source": source})
                return jsonify(error="invalid MAC address"), 400
        elif config.default_mac:
            mac = config.default_mac  # normalized when the settings were read
        else:
            return jsonify(error="no target MAC configured or supplied"), 400

        try:
            sent = send_magic_packet(mac, config.broadcast_address, config.wol_port)
        except OSError:
            LOG.exception(
                "send_failed",
                extra={
                    "mac": mac,
                    "broadcast": config.broadcast_address,
                    "port": config.wol_port,
                },
            )
            return jsonify(error="failed to send magic packet"), 502

        LOG.info(
            "packet_sent",
            extra={
                "mac": mac,
                "broadcast": config.broadcast_address,
                "port": config.wol_port,
                "bytes": sent,
                "source": source,
            },
        )
        return (
            jsonify(
                status="sent",
                mac=mac,
                broadcast=config.broadcast_address,
                port=config.wol_port,
            ),
            200,
        )

    return app


def _read_body() -> dict:
    """The request body as a JSON object; an empty body is an empty object.

    Raises ``ValueError`` (with the message for the caller) for a body that
    isn't a JSON object. Not ``get_json(silent=True)``: that turns a broken
    body into "no body", and the default machine wakes instead of the one
    the caller asked for.
    """
    raw = request.get_data()
    if not raw:
        return {}
    if not request.is_json:
        raise ValueError("Content-Type must be application/json")
    try:
        body = json.loads(raw)
    except (ValueError, RecursionError) as exc:  # includes UnicodeDecodeError
        raise ValueError("request body is not valid JSON") from exc
    if not isinstance(body, dict):
        raise ValueError("request body must be a JSON object")
    return body


def _authorized(expected_token: str) -> bool:
    # Compared as bytes: compare_digest refuses str with non-ASCII
    # characters, and a header with an umlaut would end in a 500 instead
    # of a 401.
    presented = request.headers.get(AUTH_HEADER, "")
    return hmac.compare_digest(presented.encode("utf-8", "surrogateescape"), expected_token.encode("utf-8"))


def main() -> None:
    from waitress import serve

    try:
        config = Config.from_env()
    except ConfigError as exc:
        logging_setup.configure("INFO")
        LOG.error("config_invalid", extra={"reason": str(exc)})
        raise SystemExit(1) from exc

    logging_setup.configure(config.log_level)
    LOG.info(
        "starting",
        extra={
            "version": VERSION,
            "listen": f"{config.listen_host}:{config.listen_port}",
            "broadcast": config.broadcast_address,
            "wol_port": config.wol_port,
            "default_target_configured": config.default_mac is not None,
            "body_mac_override": config.allow_body_mac,
        },
    )
    serve(
        create_app(config),
        host=config.listen_host,
        port=config.listen_port,
        ident="wol-relay",
        max_request_body_size=MAX_BODY_BYTES,
    )


if __name__ == "__main__":
    main()
