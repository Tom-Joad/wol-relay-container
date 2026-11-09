"""Container health check: ask the running relay for /health.

Reads the settings through ``Config``, so it asks on the address and port the
relay really listens on (the same defaults and fallbacks as ``app.py``).
Exits 0 when the relay answers 200, 1 otherwise.
"""

from __future__ import annotations

import sys
import urllib.request

from app import Config, ConfigError, health_url


def main() -> int:
    try:
        url = health_url(Config.from_env())
        with urllib.request.urlopen(url, timeout=3) as response:
            return 0 if response.status == 200 else 1
    except (ConfigError, OSError):
        return 1


if __name__ == "__main__":
    sys.exit(main())
