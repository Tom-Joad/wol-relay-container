import dataclasses
import threading

import pytest

from app import Config, ConfigError, create_app, health_url
from wol import build_magic_packet, normalize_mac

TOKEN = "test-token-0123456789"
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


def test_a_non_ascii_token_is_rejected_not_an_error(client):
    response = client.post("/wol", headers={"X-Auth-Token": "t\u00f6ken"})
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


@pytest.mark.parametrize("name, value", [
    ("WOL_LOG_LEVEL", "LOUD"),
    ("WOL_BROADCAST_ADDRESS", "192.168.1"),
    ("WOL_BROADCAST_ADDRESS", "broadcast.example"),
])
def test_config_rejects_a_bad_setting(name, value):
    env = {"WOL_AUTH_TOKEN": TOKEN, "WOL_TARGET_MAC": "aa:bb:cc:dd:ee:ff", name: value}
    with pytest.raises(ConfigError, match=name):
        Config.from_env(env)


def test_log_level_is_case_insensitive():
    env = {"WOL_AUTH_TOKEN": TOKEN, "WOL_TARGET_MAC": "aa:bb:cc:dd:ee:ff", "WOL_LOG_LEVEL": "debug"}
    assert Config.from_env(env).log_level == "DEBUG"


def _env(**overrides):
    return {"WOL_AUTH_TOKEN": TOKEN, "WOL_TARGET_MAC": MAC, **overrides}


@pytest.mark.parametrize(
    "token",
    [
        "abcdefghijklmnop ",  # trailing space
        " abcdefghijklmnop",
        "abcdefghijklmnop\r",  # .env saved with Windows line endings
        "abcdefghijklmnop\n",
        " " * 20,
        "t\u00f6ken-0123456789abc",  # non-ASCII
        "abcdefghijklmn\x00p",
        "abcdefghijklmno",  # 15 characters
        "x",
    ],
)
def test_config_refuses_a_token_that_could_never_match_or_is_too_short(token):
    with pytest.raises(ConfigError, match="WOL_AUTH_TOKEN"):
        Config.from_env(_env(WOL_AUTH_TOKEN=token))


def test_config_accepts_a_16_character_token_with_inner_spaces():
    token = "abc def ghi jkl!"
    assert Config.from_env(_env(WOL_AUTH_TOKEN=token)).auth_token == token


def test_a_non_ascii_header_never_matches_and_a_latin1_header_is_no_error(client):
    for value in ("t\u00f6ken-0123456789", "\u20ac" * 20):
        response = client.post("/wol", headers={"X-Auth-Token": value})
        assert response.status_code == 401


@pytest.mark.parametrize(
    "raw, expected",
    [
        (None, "0.0.0.0"),
        ("", "0.0.0.0"),
        ("  ", "0.0.0.0"),
        (" 192.168.1.20 ", "192.168.1.20"),
        ("127.0.0.1", "127.0.0.1"),
        ("localhost", "localhost"),
        ("::1", "::1"),
    ],
)
def test_listen_host_is_stripped_and_defaulted(raw, expected):
    env = _env() if raw is None else _env(WOL_LISTEN_HOST=raw)
    assert Config.from_env(env).listen_host == expected


@pytest.mark.parametrize("raw", ["192.168.1.300", "relay.example", "0.0.0", "1.2.3.4:80"])
def test_config_rejects_a_bad_listen_host_naming_the_setting(raw):
    with pytest.raises(ConfigError, match="WOL_LISTEN_HOST"):
        Config.from_env(_env(WOL_LISTEN_HOST=raw))


def test_main_reports_a_bad_listen_host_as_config_invalid(monkeypatch, capsys):
    import app as app_module

    monkeypatch.setenv("WOL_AUTH_TOKEN", TOKEN)
    monkeypatch.setenv("WOL_LISTEN_HOST", "192.168.1.300")
    with pytest.raises(SystemExit):
        app_module.main()
    assert '"event":"config_invalid"' in capsys.readouterr().out


@pytest.mark.parametrize(
    "env, url",
    [
        ({}, "http://127.0.0.1:8099/health"),
        ({"WOL_LISTEN_PORT": ""}, "http://127.0.0.1:8099/health"),
        ({"WOL_LISTEN_PORT": "9100"}, "http://127.0.0.1:9100/health"),
        ({"WOL_LISTEN_HOST": ""}, "http://127.0.0.1:8099/health"),
        ({"WOL_LISTEN_HOST": "0.0.0.0"}, "http://127.0.0.1:8099/health"),
        ({"WOL_LISTEN_HOST": "172.31.250.10"}, "http://172.31.250.10:8099/health"),
        ({"WOL_LISTEN_HOST": "localhost"}, "http://localhost:8099/health"),
        ({"WOL_LISTEN_HOST": "::"}, "http://[::1]:8099/health"),
        ({"WOL_LISTEN_HOST": "fd00::5"}, "http://[fd00::5]:8099/health"),
    ],
)
def test_health_url_follows_the_listen_settings(env, url):
    assert health_url(Config.from_env(_env(**env))) == url


def test_the_healthcheck_asks_the_address_the_relay_listens_on(monkeypatch):
    """Real HTTP on loopback: healthcheck.py finds a relay bound to 127.0.0.2."""
    from waitress.server import create_server

    import healthcheck

    config = Config.from_env(_env(WOL_LISTEN_HOST="127.0.0.2", WOL_LISTEN_PORT="1"))
    server = create_server(create_app(config), host="127.0.0.2", port=0)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv("WOL_AUTH_TOKEN", TOKEN)
        monkeypatch.setenv("WOL_LISTEN_HOST", "127.0.0.2")
        monkeypatch.setenv("WOL_LISTEN_PORT", str(server.effective_port))
        assert healthcheck.main() == 0
        monkeypatch.setenv("WOL_LISTEN_HOST", "127.0.0.1")  # nothing listens there
        assert healthcheck.main() == 1
    finally:
        server.close()
        thread.join(timeout=5)


def test_the_healthcheck_fails_on_invalid_settings(monkeypatch):
    import healthcheck

    monkeypatch.delenv("WOL_AUTH_TOKEN", raising=False)
    assert healthcheck.main() == 1
