import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

import logging_setup

ENTRYPOINT = Path(__file__).resolve().parent.parent / "docker-entrypoint.sh"


def _format(created: float) -> dict:
    record = logging.LogRecord("t", logging.INFO, "", 0, "event", None, None)
    record.created = created
    return json.loads(logging_setup.JsonFormatter().format(record))


@pytest.fixture
def tz(monkeypatch):
    def set_tz(name):
        monkeypatch.setenv("TZ", name)
        time.tzset()

    yield set_tz
    monkeypatch.undo()
    time.tzset()


def test_timestamp_is_utc_with_z_by_default(tz):
    tz("UTC")
    assert _format(0)["ts"] == "1970-01-01T00:00:00.000Z"


def test_timestamp_follows_tz(tz):
    tz("Europe/Berlin")
    assert _format(1767268800)["ts"] == "2026-01-01T13:00:00.000+01:00"


def _run(env, *cmd):
    return subprocess.run(
        ["sh", str(ENTRYPOINT), *cmd],
        env={"PATH": os.environ["PATH"], **env},
        capture_output=True,
        text=True,
    )


@pytest.mark.skipif(os.getuid() != 0, reason="the IDs are only checked when started as root")
@pytest.mark.parametrize("env", [{"PUID": "abc"}, {"PGID": "1 0"}, {"PUID": "0"}, {"PGID": "0"}])
def test_entrypoint_rejects_bad_ids(env):
    result = _run(env, "true")
    assert result.returncode == 1
    assert "PUID" in result.stderr or "PGID" in result.stderr


@pytest.mark.skipif(os.getuid() == 0, reason="as root the entrypoint switches users")
def test_entrypoint_runs_the_command_when_not_root():
    result = _run({"PUID": "0"}, "echo", "hello")
    assert result.returncode == 0
    assert result.stdout.strip() == "hello"


@pytest.mark.skipif(
    os.getuid() != 0 or shutil.which("su-exec") is None, reason="needs root and su-exec"
)
def test_entrypoint_drops_to_puid_and_pgid():
    result = _run({"PUID": "4242", "PGID": "4343"}, "id", "-u")
    assert result.stdout.strip() == "4242"
