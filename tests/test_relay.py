import dataclasses
import logging
import threading
import urllib.error
import urllib.request

import pytest

from app import MAX_BODY_BYTES, Config, ConfigError, FailureThrottle, create_app
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
    env = {"WOL_AUTH_TOKEN": "t", "WOL_TARGET_MAC": "aa:bb:cc:dd:ee:ff", name: value}
    with pytest.raises(ConfigError, match=name):
        Config.from_env(env)


def test_log_level_is_case_insensitive():
    env = {"WOL_AUTH_TOKEN": "t", "WOL_TARGET_MAC": "aa:bb:cc:dd:ee:ff", "WOL_LOG_LEVEL": "debug"}
    assert Config.from_env(env).log_level == "DEBUG"


def _post(client, data, content_type="application/json"):
    return client.post(
        "/wol", headers={"X-Auth-Token": TOKEN}, data=data, content_type=content_type
    )


def _assert_nothing_sent(client):
    assert client.application.config["SENT"] == []


@pytest.mark.parametrize(
    "data, content_type",
    [
        (b'{"mac":"11:22:33:44:55:66"', "application/json"),  # truncated
        (b"not json", "application/json"),
        (b"\xff\xfe", "application/json"),  # not UTF-8
        (b'{"mac":"11:22:33:44:55:66"}', "application/x-www-form-urlencoded"),
        (b'{"mac":"11:22:33:44:55:66"}', "text/plain"),
        (b"[" * 2000 + b"]" * 2000, "application/json"),  # deeply nested
        (b'["a"]', "application/json"),
        (b"null", "application/json"),
    ],
)
def test_a_body_that_is_not_a_json_object_is_a_400_and_wakes_nothing(client, data, content_type):
    response = _post(client, data, content_type)
    assert response.status_code == 400
    _assert_nothing_sent(client)


def test_a_body_that_exhausts_the_json_parser_is_a_400(client, monkeypatch):
    def too_deep(_raw):
        raise RecursionError

    monkeypatch.setattr("app.json.loads", too_deep)
    assert _post(client, b"[[[").status_code == 400
    _assert_nothing_sent(client)


def test_an_empty_body_uses_the_default_target(client):
    response = _post(client, b"", "application/json")
    assert response.status_code == 200
    assert response.get_json()["mac"] == MAC


@pytest.mark.parametrize("value", ["", 0, False, None, 5, []])
def test_a_supplied_mac_that_is_falsy_is_an_invalid_mac_not_the_default(client, value):
    response = client.post("/wol", headers={"X-Auth-Token": TOKEN}, json={"mac": value})
    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid MAC address"}
    _assert_nothing_sent(client)


def test_the_source_of_the_target_is_logged(client, caplog):
    with caplog.at_level(logging.INFO, logger="wol-relay"):
        client.post("/wol", headers={"X-Auth-Token": TOKEN})
        client.post("/wol", headers={"X-Auth-Token": TOKEN}, json={"mac": "11:22:33:44:55:66"})
    sources = [r.source for r in caplog.records if r.getMessage() == "packet_sent"]
    assert sources == ["env", "body"]


def test_an_oversized_body_is_a_413(client):
    response = _post(client, b"{" + b" " * MAX_BODY_BYTES + b"}")
    assert response.status_code == 413
    _assert_nothing_sent(client)


def test_waitress_refuses_a_large_unauthenticated_body_before_buffering_it(config, monkeypatch):
    """Over real HTTP on loopback: waitress answers 413 before the app runs."""
    from waitress.server import create_server

    from app import MAX_BODY_BYTES as limit

    monkeypatch.setattr("app.send_magic_packet", lambda *a: pytest.fail("sent a packet"))
    server = create_server(
        create_app(config), host="127.0.0.1", port=0, max_request_body_size=limit
    )
    port = server.effective_port
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/wol", data=b"x" * 600_000, method="POST"
        )
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(request, timeout=5)
        assert excinfo.value.code == 413
    finally:
        server.close()
        thread.join(timeout=5)


def test_main_passes_the_body_limit_to_waitress(monkeypatch):
    import app as app_module

    captured = {}
    monkeypatch.setattr("waitress.serve", lambda wsgi, **kwargs: captured.update(kwargs))
    monkeypatch.setenv("WOL_AUTH_TOKEN", TOKEN)
    app_module.main()
    assert captured["max_request_body_size"] == MAX_BODY_BYTES


def _fail(client, count, address="10.0.0.1"):
    return [
        client.post(
            "/wol", headers={"X-Auth-Token": "wrong"}, environ_base={"REMOTE_ADDR": address}
        ).status_code
        for _ in range(count)
    ]


def test_failed_tokens_are_throttled_per_address(client):
    assert _fail(client, 20) == [401] * 20
    blocked = client.post(
        "/wol", headers={"X-Auth-Token": "wrong"}, environ_base={"REMOTE_ADDR": "10.0.0.1"}
    )
    assert blocked.status_code == 429
    assert 1 <= int(blocked.headers["Retry-After"]) <= 900

    # Also a good token from that address, but not another address.
    good = client.post(
        "/wol", headers={"X-Auth-Token": TOKEN}, environ_base={"REMOTE_ADDR": "10.0.0.1"}
    )
    assert good.status_code == 429
    other = client.post(
        "/wol", headers={"X-Auth-Token": TOKEN}, environ_base={"REMOTE_ADDR": "10.0.0.2"}
    )
    assert other.status_code == 200
    assert len(client.application.config["SENT"]) == 1


def test_a_good_token_takes_its_attempt_back(client):
    assert _fail(client, 19) == [401] * 19
    good = client.post(
        "/wol", headers={"X-Auth-Token": TOKEN}, environ_base={"REMOTE_ADDR": "10.0.0.1"}
    )
    assert good.status_code == 200
    # The good request was not counted: the 20th failure is still allowed.
    assert _fail(client, 1) == [401]
    assert _fail(client, 1) == [429]


def test_a_restart_clears_the_throttle(config, monkeypatch):
    monkeypatch.setattr("app.send_magic_packet", lambda *a: 102)
    first = create_app(config).test_client()
    _fail(first, 21)
    assert _fail(first, 1) == [429]
    second = create_app(config).test_client()
    assert _fail(second, 1) == [401]


def test_auth_rejected_logs_the_client_and_the_throttle_logs_once(client, caplog):
    with caplog.at_level(logging.WARNING, logger="wol-relay"):
        _fail(client, 25)
    rejected = [r for r in caplog.records if r.getMessage() == "auth_rejected"]
    throttled = [r for r in caplog.records if r.getMessage() == "auth_throttled"]
    assert len(rejected) == 20
    assert {r.client for r in rejected} == {"10.0.0.1"}
    assert len(throttled) == 1
    assert throttled[0].client == "10.0.0.1"


class _Clock:
    now = 1000.0

    def __call__(self):
        return self.now


def test_throttle_forgets_failures_after_the_window():
    clock = _Clock()
    throttle = FailureThrottle(limit=2, window=60, clock=clock)
    assert throttle.attempt("a") == (0, False)
    assert throttle.attempt("a") == (0, False)
    assert throttle.attempt("a") == (60, True)
    assert throttle.attempt("a") == (60, False)  # logged once per window
    clock.now += 59
    assert throttle.attempt("a")[0] == 1
    clock.now += 1
    assert throttle.attempt("a") == (0, False)


def test_throttle_caps_the_number_of_tracked_addresses():
    throttle = FailureThrottle(limit=1, window=60, max_addresses=3, clock=_Clock())
    for address in "abcdef":
        throttle.attempt(address)
    assert len(throttle._failures) <= 3
