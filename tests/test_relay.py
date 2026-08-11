import dataclasses

import pytest

from app import Config, ConfigError, create_app
from wol import build_magic_packet, normalize_mac

TOKEN = "test-token"
MAC = "aa:bb:cc:dd:ee:ff"


@pytest.fixture
def config():
    return Config(
        auth_token=TOKEN,
        default_mac=MAC,
        broadcast_address="255.255.255.255",
        wol_port=9,
        listen_host="127.0.0.1",
        listen_port=8099,
        log_level="INFO",
        allow_body_mac=True,
    )


@pytest.fixture
def client(config, monkeypatch):
    sent = []
    monkeypatch.setattr(
        "app.send_magic_packet",
        lambda mac, broadcast, port: sent.append((mac, broadcast, port)) or 102,
    )
    app = create_app(config)
    app.config["SENT"] = sent
    return app.test_client()


@pytest.mark.parametrize(
    "raw",
    ["aa:bb:cc:dd:ee:ff", "AA-BB-CC-DD-EE-FF", "aabb.ccdd.eeff", "AABBCCDDEEFF"],
)
def test_normalize_mac_accepts_common_spellings(raw):
    assert normalize_mac(raw) == MAC


@pytest.mark.parametrize("raw", ["", "aa:bb:cc:dd:ee", "zz:bb:cc:dd:ee:ff", "aabbccddeeff11"])
def test_normalize_mac_rejects_garbage(raw):
    with pytest.raises(ValueError):
        normalize_mac(raw)


def test_magic_packet_layout():
    packet = build_magic_packet(MAC)
    assert len(packet) == 102
    assert packet[:6] == b"\xff" * 6
    assert packet[6:] == bytes.fromhex("aabbccddeeff") * 16


def test_health_needs_no_token(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_missing_token_is_rejected(client):
    assert client.post("/wol").status_code == 401


def test_wrong_token_is_rejected(client):
    response = client.post("/wol", headers={"X-Auth-Token": "nope"})
    assert response.status_code == 401


def test_default_target_is_used(client):
    response = client.post("/wol", headers={"X-Auth-Token": TOKEN})
    assert response.status_code == 200
    assert response.get_json()["mac"] == MAC


def test_body_overrides_target(client):
    response = client.post(
        "/wol",
        headers={"X-Auth-Token": TOKEN},
        json={"mac": "11-22-33-44-55-66"},
    )
    assert response.status_code == 200
    assert response.get_json()["mac"] == "11:22:33:44:55:66"


def test_invalid_body_mac_is_rejected(client):
    response = client.post("/wol", headers={"X-Auth-Token": TOKEN}, json={"mac": "nope"})
    assert response.status_code == 400


def test_body_override_can_be_disabled(config, monkeypatch):
    monkeypatch.setattr("app.send_magic_packet", lambda *args: 102)
    client = create_app(dataclasses.replace(config, allow_body_mac=False)).test_client()
    response = client.post("/wol", headers={"X-Auth-Token": TOKEN}, json={"mac": MAC})
    assert response.status_code == 400


def test_send_failure_reports_502(config, monkeypatch):
    def boom(*args):
        raise OSError("network unreachable")

    monkeypatch.setattr("app.send_magic_packet", boom)
    client = create_app(config).test_client()
    response = client.post("/wol", headers={"X-Auth-Token": TOKEN})
    assert response.status_code == 502


def test_config_requires_a_token():
    with pytest.raises(ConfigError):
        Config.from_env({})


def test_config_rejects_a_broken_mac():
    with pytest.raises(ConfigError):
        Config.from_env({"WOL_AUTH_TOKEN": TOKEN, "WOL_TARGET_MAC": "nope"})


def test_config_defaults():
    config = Config.from_env({"WOL_AUTH_TOKEN": TOKEN, "WOL_TARGET_MAC": MAC})
    assert config.broadcast_address == "255.255.255.255"
    assert config.wol_port == 9
    assert config.listen_port == 8099
    assert config.allow_body_mac is True
