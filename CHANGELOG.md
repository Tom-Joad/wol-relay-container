# Changelog

All notable changes to this project are listed here. Versions follow
[semantic versioning](https://semver.org/).

## [3.0.0] - 2026-11-12

### Changed
- A MAC address (`mac` in the body, `WOL_TARGET_MAC`) is accepted only in
  the documented spellings: `aa:bb:cc:dd:ee:ff`, `aa-bb-cc-dd-ee-ff`,
  `aabb.ccdd.eeff` or `aabbccddeeff`, in either case. Before, any mix of
  separators was taken as long as twelve hex digits were left, for example
  `aabbcc:ddeeff`. **Upgrade note:** a `WOL_TARGET_MAC` in another spelling
  now stops the container with `config_invalid`; write it as above.
- A JSON body with the same key twice (`{"mac": …, "mac": …}`) gets `400`.
  Before, the last one counted, which another parser in front of the relay
  might read differently.
- Every answer is JSON, `404` and `405` included, and carries
  `Cache-Control: no-store` and `X-Content-Type-Options: nosniff`.
- `requirements.txt` pins the packages Flask pulls in as well (Werkzeug,
  Jinja2, MarkupSafe, click, itsdangerous, blinker), so every build
  installs the same versions. The versions are the ones the 2.0.0 image
  already has.

### Fixed
- The health check ignores `http_proxy`. Before, a proxy set in the
  container's environment received the check, and the container stayed
  `unhealthy` while the relay worked.
- The `starting` line is logged with every `WOL_LOG_LEVEL`. Before,
  `WARNING` or `ERROR` dropped it.
- README: a new "Upgrading from 1.x" section, a development example whose
  token is long enough to start, and no stale note about swapping `build:`
  for `image:`. The Unraid template names the 16-character token minimum.

### Security
- `PUID` or `PGID` of 4294967296 or more is refused. Before, `su-exec` kept
  only the low 32 bits of the ID, so `PUID=4294967296` ran the relay as
  root. IDs from 1 to 4294967294 are accepted, leading zeros are ignored.
- `.env.example` no longer carries a placeholder token, and the placeholder
  it used to carry (`replace-with-a-long-random-secret`) stops the container
  with `config_invalid`. Before, `cp .env.example .env` without editing the
  token started a relay that accepted a token anyone could read in the
  repository. **Upgrade note:** if your relay stops with this message, set
  your own token (`openssl rand -hex 32`) in the relay and in its callers.
- Idle connections are closed after 10 seconds instead of 120. Before, 100
  idle connections, no token needed, shut out every caller and the health
  check for two minutes at a time. Someone who keeps reopening them can
  still crowd the relay out; keep it on a trusted network, as before.
- The relay itself refuses to start as root (`config_invalid`), whatever
  way the entrypoint's check was passed.

## [2.0.0] - 2026-11-10

### Changed
- `WOL_AUTH_TOKEN` is checked at start: a token with leading or trailing
  whitespace (for example the `\r` of a `.env` saved with Windows line
  endings), with characters outside printable ASCII, or shorter than 16
  characters stops the container with `config_invalid`. Before, such a token
  started fine and then answered `401` to every request (or was easy to
  guess). **Upgrade note:** a shorter token must be replaced
  (`openssl rand -hex 32`) in the relay and in its callers.
- The presented token is read as latin-1, the way WSGI hands headers over,
  instead of UTF-8.
- CI: `docker/login-action` moves to v4.8.0, and the security watch follows
  the current shared template: an unreachable package index counts as an
  unreachable source instead of ending the run, the release tag is the
  merged release commit, only a dated changelog heading counts as released,
  Debian versions compare like dpkg, and merging the release pull request no
  longer closes issues (the watch closes an "available" issue itself once the
  published image is fixed). No change to the image.

### Security
- A zero-padded `PUID` or `PGID` (`00`, `000`) is refused like `0`. Before,
  the entrypoint compared the text with `0`, and `su-exec` then ran the
  relay as root.
- Request bodies are limited to 4 KiB. Anything bigger gets `413` before it
  is buffered; before, a large body without a token ended in an error log
  line under `--read-only`, or wrote up to 1 GiB into the container's
  writable layer.
- Wrong tokens are counted per client address. After 20 in 15 minutes the
  address gets `429` with `Retry-After` (also for a correct token) until the
  window passes. The count lives in memory and a restart clears it.
- `auth_rejected` log lines name the client address.

### Fixed
- The health check asks on the address and port the relay listens on. Before,
  it always used `127.0.0.1` and the raw `WOL_LISTEN_PORT`, so a container
  with `WOL_LISTEN_HOST` set to one address, or with an empty
  `WOL_LISTEN_PORT`, stayed `unhealthy` while it served requests.
- `WOL_LISTEN_HOST` is stripped, an empty value means `0.0.0.0`, and
  anything that is not an IP address or `localhost` stops the start with
  `config_invalid` naming the setting. Before, an empty or mistyped value
  ended in a waitress traceback.
- README: the deployment section starts the prebuilt image with
  `docker compose up -d` and describes building it yourself as the
  alternative.
- A body that isn't valid JSON (truncated, not UTF-8, deeply nested), is not
  a JSON object, or comes without `Content-Type: application/json` gets
  `400`. Before, the relay treated it as "no body", answered `200` and woke
  the default machine instead of the one the caller asked for. An empty body
  still means the default target.
- `{"mac": ""}` (or `0`, `false`, `null`) is an invalid MAC address. Before,
  it was read as "no MAC supplied". The `source` log field now follows
  whether a `mac` was sent.

## [1.0.8] - 2026-11-07

### Changed
- The base image moves to the rebuilt `python:3.14-alpine` (digest `a18b20a`,
  still Python 3.14.10): Alpine 3.24.4, `apk-tools` 3.0.9, `tzdata` 2026f.

## [1.0.7] - 2026-11-03

### Security
- The base image moves to Python 3.14.10 (was 3.14.8), with the security
  fixes of Python 3.14.9 and 3.14.10.

## [1.0.6] - 2026-10-22

### Changed
- The build upgrades the Alpine packages before installing anything, so
  every image has the current fixes, not only those of the pinned base
  image. Before, packages the base image ships (such as musl, brotli,
  c-ares and ca-certificates) stayed at its state until the next base
  image update.

### Security
- Security updates of the distribution packages, picked up by rebuilding the image:
  - `musl` 1.2.6-r3 (CVE-2026-107891)

## [1.0.5] - 2026-10-20

### Fixed
- An unknown `WOL_LOG_LEVEL` stops the start with a `config_invalid` line
  that names the setting, instead of a Python traceback.
- `WOL_BROADCAST_ADDRESS` is checked at start: anything but an IPv4
  address stops the container with `config_invalid`, instead of showing up
  as a `502` on the first wake-up. The log level is no longer
  case-sensitive.

## [1.0.4] - 2026-10-19

### Changed
- The `starting` log line names the version.
- `docker-compose.yml` uses the published image.
- Images are published only for releases (`v*` tags), no longer for every
  push to `main`. `latest` now always points to the newest release; before,
  a push to `main` could overwrite it.

### Fixed
- A token header with non-ASCII characters is answered with 401 instead of
  an internal error (500).

## [1.0.3] - 2026-10-12

### Security
- pip is removed from the image after the requirements are installed. The
  libraries it bundles (`urllib3`, `msgpack`) had known high-severity issues
  in 1.0.2; the relay itself never used them.

## [1.0.2] - 2026-10-12

### Changed
- The image is based on `python:3.14-alpine` (was `python:3.12-alpine`),
  pinned by digest so Dependabot proposes updates.
- CI builds the image on every push and pull request and runs a smoke test
  against it, hardened as in `docker-compose.yml`.

## [1.0.1] - 2026-10-03

### Changed
- CI: `docker/build-push-action` 7.4.0, `docker/metadata-action` 6.2.0 and
  `sigstore/cosign-installer` 4.1.2 (signs with cosign 3.0.6). Images are
  still verifiable with the `cosign verify` command from the README.
- The image content is unchanged from 1.0.0.

## [1.0.0] - 2026-10-03

First stable release. Settings, endpoints and the log format are now stable;
a change that needs action when upgrading only comes with a new major version.

### Added
- `PUID` and `PGID` (default 1000): the container starts as root, the
  entrypoint switches to these IDs with `su-exec` and the relay runs as that
  user. `0` is refused. `--read-only` keeps working, and all capabilities
  except `SETUID` and `SETGID` can be dropped.
- `TZ` (default `Etc/UTC`), backed by `tzdata`.
- Unraid template in `unraid/`.
- `SECURITY.md`, issue templates, this changelog and Dependabot configuration
  (pip, docker, github-actions).

### Changed
- Log time stamps are local time with a UTC offset according to `TZ`, for
  example `2026-01-01T13:00:00.000+01:00`. With the default `TZ` they are
  unchanged (`…Z`).
- The image no longer ships a fixed `relay` user (UID 10001). Set `PUID` and
  `PGID` if you relied on that ID.
- CI: actions updated to their Node 24 releases; the test job gets
  `pull-requests: read` so gitleaks works on pull requests.

[3.0.0]: https://github.com/Tom-Joad/wol-relay-container/compare/v2.0.0...v3.0.0
[2.0.0]: https://github.com/Tom-Joad/wol-relay-container/compare/v1.0.8...v2.0.0
[1.0.8]: https://github.com/Tom-Joad/wol-relay-container/compare/v1.0.7...v1.0.8
[1.0.7]: https://github.com/Tom-Joad/wol-relay-container/compare/v1.0.6...v1.0.7
[1.0.6]: https://github.com/Tom-Joad/wol-relay-container/compare/v1.0.5...v1.0.6
[1.0.5]: https://github.com/Tom-Joad/wol-relay-container/compare/v1.0.4...v1.0.5
[1.0.4]: https://github.com/Tom-Joad/wol-relay-container/compare/v1.0.3...v1.0.4
[1.0.3]: https://github.com/Tom-Joad/wol-relay-container/compare/v1.0.2...v1.0.3
[1.0.2]: https://github.com/Tom-Joad/wol-relay-container/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/Tom-Joad/wol-relay-container/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/Tom-Joad/wol-relay-container/releases/tag/v1.0.0
