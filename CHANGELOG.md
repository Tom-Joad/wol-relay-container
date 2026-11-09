# Changelog

All notable changes to this project are listed here. Versions follow
[semantic versioning](https://semver.org/).

## [Unreleased]

### Changed
- CI: `docker/login-action` moves to v4.8.0, and the security watch follows
  the current shared template: an unreachable package index counts as an
  unreachable source instead of ending the run, the release tag is the
  merged release commit, only a dated changelog heading counts as released,
  Debian versions compare like dpkg, and merging the release pull request no
  longer closes issues (the watch closes an "available" issue itself once the
  published image is fixed). No change to the image.

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

[1.0.8]: https://github.com/Tom-Joad/wol-relay-container/compare/v1.0.7...v1.0.8
[1.0.7]: https://github.com/Tom-Joad/wol-relay-container/compare/v1.0.6...v1.0.7
[1.0.6]: https://github.com/Tom-Joad/wol-relay-container/compare/v1.0.5...v1.0.6
[1.0.5]: https://github.com/Tom-Joad/wol-relay-container/compare/v1.0.4...v1.0.5
[1.0.4]: https://github.com/Tom-Joad/wol-relay-container/compare/v1.0.3...v1.0.4
[1.0.3]: https://github.com/Tom-Joad/wol-relay-container/compare/v1.0.2...v1.0.3
[1.0.2]: https://github.com/Tom-Joad/wol-relay-container/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/Tom-Joad/wol-relay-container/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/Tom-Joad/wol-relay-container/releases/tag/v1.0.0
