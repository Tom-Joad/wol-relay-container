"""HTTP relay that turns an authenticated POST into a Wake-on-LAN packet.

All deployment specifics (token, target MAC, broadcast address, ports) come
from environment variables at runtime. Nothing is hardcoded.
"""

from __future__ import annotations

import hmac
import logging
import os
from dataclasses import dataclass

from flask import Flask, jsonify, request

import logging_setup
from wol import normalize_mac, send_magic_packet

LOG = logging.getLogger("wol-relay")

AUTH_HEADER = "X-Auth-Token"


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

        return cls(
            auth_token=token,
            default_mac=default_mac,
            broadcast_address=env.get("WOL_BROADCAST_ADDRESS", "255.255.255.255"),
            wol_port=_int_env(env, "WOL_PORT", 9),
            listen_host=env.get("WOL_LISTEN_HOST", "0.0.0.0"),
            listen_port=_int_env(env, "WOL_LISTEN_PORT", 8099),
            log_level=env.get("WOL_LOG_LEVEL", "INFO"),
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


def create_app(config: Config | None = None) -> Flask:
    config = Config.from_env() if config is None else config

    app = Flask(__name__)
    app.config["WOL_RELAY"] = config

    @app.get("/health")
    def health():
        return jsonify(status="ok"), 200

    @app.post("/wol")
    def wake():
        if not _authorized(config.auth_token):
            LOG.warning("auth_rejected", extra={"path": "/wol"})
            return jsonify(error="unauthorized"), 401

        body = request.get_json(silent=True)
        if body is None:
            body = {}
        if not isinstance(body, dict):
            return jsonify(error="request body must be a JSON object"), 400

        requested_mac = body.get("mac")
        if requested_mac is not None and not config.allow_body_mac:
            LOG.warning("body_mac_refused")
            return jsonify(error="per-request MAC override is disabled"), 400

        raw_mac = requested_mac if requested_mac is not None else config.default_mac
        if not raw_mac:
            return jsonify(error="no target MAC configured or supplied"), 400

        try:
            mac = normalize_mac(raw_mac)
        except ValueError:
            LOG.warning("invalid_mac", extra={"source": "body" if requested_mac else "env"})
            return jsonify(error="invalid MAC address"), 400

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
                "source": "body" if requested_mac else "env",
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


def _authorized(expected_token: str) -> bool:
    presented = request.headers.get(AUTH_HEADER, "")
    return hmac.compare_digest(presented, expected_token)


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
    )


if __name__ == "__main__":
    main()
