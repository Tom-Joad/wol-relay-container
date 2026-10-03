# Changelog

All notable changes to this project are listed here. Versions follow
[semantic versioning](https://semver.org/).

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

[1.0.1]: https://github.com/Tom-Joad/wol-relay-container/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/Tom-Joad/wol-relay-container/releases/tag/v1.0.0
