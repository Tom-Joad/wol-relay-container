# wol-relay-container

[![Build and push image](https://github.com/Tom-Joad/wol-relay-container/actions/workflows/build-and-push.yml/badge.svg)](https://github.com/Tom-Joad/wol-relay-container/actions/workflows/build-and-push.yml)

A small HTTP relay that sends a Wake-on-LAN magic packet when it receives an
authenticated request. Built as a trigger target for Home Assistant, but it is
plain HTTP and works with anything that can issue a `POST`.

The container runs with `network_mode: host` on a Docker host that sits in the
same layer 2 segment as the machine to be woken, so the UDP broadcast reaches
the target without macvlan or bridge gymnastics.

Everything environment-specific — the shared secret, the target MAC, the
broadcast address, the ports — is supplied through environment variables at
runtime. The repository contains no real values.

## Endpoints

| Method | Path      | Auth              | Purpose                          |
| ------ | --------- | ----------------- | -------------------------------- |
| `POST` | `/wol`    | `X-Auth-Token`    | Send a magic packet              |
| `GET`  | `/health` | none              | Liveness probe                   |

`POST /wol` accepts an optional JSON body. Without one, the magic packet goes
to `WOL_TARGET_MAC`:

```json
{ "mac": "aa:bb:cc:dd:ee:ff" }
```

The `mac` field accepts `aa:bb:cc:dd:ee:ff`, `AA-BB-CC-DD-EE-FF`,
`aabb.ccdd.eeff` and `aabbccddeeff`. Set `WOL_ALLOW_BODY_MAC=false` to refuse
per-request overrides and pin the relay to its configured target.

### Responses

| Status | Meaning                                                        |
| ------ | -------------------------------------------------------------- |
| `200`  | Packet sent — body echoes `mac`, `broadcast` and `port`         |
| `400`  | Malformed body, invalid MAC, or no target configured/supplied   |
| `401`  | Missing or wrong `X-Auth-Token`                                 |
| `502`  | The datagram could not be sent (socket error)                   |

A `200` means the packet left the host. Wake-on-LAN is fire-and-forget: it is
not a confirmation that the target actually woke up.

## Parameters

Parameters follow the [linuxserver.io](https://docs.linuxserver.io/) style.

| Parameter                       | Function                                                          |
| ------------------------------- | ----------------------------------------------------------------- |
| `--network host`                | Required: the broadcast must reach the target's layer 2 segment    |
| `-e PUID=1000`                  | User ID the relay runs as; never `0`                               |
| `-e PGID=1000`                  | Group ID the relay runs as; never `0`                              |
| `-e TZ=Etc/UTC`                 | Time zone, e.g. `Europe/Berlin`; log time stamps follow it         |
| `-e WOL_AUTH_TOKEN=`            | Shared secret, required (see the table below)                      |
| `--read-only`                   | Supported: the relay writes no files                               |
| `--cap-drop ALL --cap-add SETUID --cap-add SETGID` | Supported: all the entrypoint needs to switch to `PUID:PGID` |

```bash
docker run -d --name wol-relay --restart unless-stopped \
  --network host --read-only \
  --cap-drop ALL --cap-add SETUID --cap-add SETGID \
  --security-opt no-new-privileges:true \
  -e PUID=1000 -e PGID=1000 -e TZ=Europe/Berlin \
  -e WOL_AUTH_TOKEN=... -e WOL_TARGET_MAC=aa:bb:cc:dd:ee:ff \
  ghcr.io/tom-joad/wol-relay-container:latest
```

The container starts as root only so the entrypoint can switch to `PUID:PGID`;
the relay itself never runs as root, and `PUID`/`PGID` of `0` abort the start.
Started with `--user`, the container runs as that user and ignores both. This
image deliberately does not use the linuxserver.io base image (s6-overlay,
docker mods): the relay is stateless, and the small Alpine image keeps
`read_only` and a minimal set of capabilities.

## Environment variables

| Variable                | Required | Default           | Description                                                        |
| ----------------------- | -------- | ----------------- | ------------------------------------------------------------------ |
| `WOL_AUTH_TOKEN`        | yes      | —                 | Shared secret expected in the `X-Auth-Token` header                 |
| `WOL_TARGET_MAC`        | no\*     | —                 | Default target MAC address                                          |
| `WOL_ALLOW_BODY_MAC`    | no       | `true`            | Allow `{"mac": "..."}` in the request body to override the target   |
| `WOL_BROADCAST_ADDRESS` | no       | `255.255.255.255` | Broadcast destination; a subnet broadcast also works                |
| `WOL_PORT`              | no       | `9`               | UDP port the magic packet is sent to (typically 9 or 7)             |
| `WOL_LISTEN_HOST`       | no       | `0.0.0.0`         | HTTP bind address                                                   |
| `WOL_LISTEN_PORT`       | no       | `8099`            | HTTP bind port                                                      |
| `WOL_LOG_LEVEL`         | no       | `INFO`            | `DEBUG`, `INFO`, `WARNING` or `ERROR`                               |

\* Either `WOL_TARGET_MAC` must be set or `WOL_ALLOW_BODY_MAC` must stay
enabled — otherwise the relay has no way to learn a target and refuses to
start. An invalid value in any variable also aborts startup with a logged
reason rather than failing on the first request.

## Deployment

```bash
cp .env.example .env
```

Fill in `.env` — at minimum `WOL_AUTH_TOKEN` and `WOL_TARGET_MAC`. Generate a
token with:

```bash
openssl rand -hex 32
```

Then:

```bash
docker compose up -d --build
```

`network_mode: host` is a Linux-only Docker feature. On Docker Desktop for
macOS or Windows the container does not share the host's layer 2 segment and
the broadcast will not reach the target.

### Prebuilt image

```bash
docker pull ghcr.io/tom-joad/wol-relay-container:latest
```

Every push to `main` builds and publishes `linux/amd64` and `linux/arm64`
images to `ghcr.io/tom-joad/wol-relay-container`, tagged `latest` plus
`sha-<commit>`; a `v*` tag additionally publishes the semver tags. Images carry
a build provenance attestation and an SBOM, and are signed keylessly with
cosign:

```bash
cosign verify ghcr.io/tom-joad/wol-relay-container:latest \
  --certificate-identity-regexp "^https://github.com/Tom-Joad/wol-relay-container/" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

To deploy that image instead of building locally, swap `build: .` for the
`image:` line in [docker-compose.yml](docker-compose.yml).

The pipeline runs the test suite, a `pip-audit` dependency check and a gitleaks
secret scan first — nothing reaches the registry unless all three pass. The
built image is then scanned with Trivy, in report-only mode so a fresh
base-image CVE cannot block a fix from shipping.

## Example request

```bash
curl -sS -X POST http://HOST_ADDRESS:8099/wol \
  -H "X-Auth-Token: $WOL_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"mac": "aa:bb:cc:dd:ee:ff"}'
```

Using the configured default target instead:

```bash
curl -sS -X POST http://HOST_ADDRESS:8099/wol -H "X-Auth-Token: $WOL_AUTH_TOKEN"
```

## Home Assistant

Put the secret in `secrets.yaml` rather than in `configuration.yaml`:

```yaml
# secrets.yaml
wol_relay_url: "http://HOST_ADDRESS:8099/wol"
wol_relay_token: "YOUR_SHARED_SECRET"
```

```yaml
# configuration.yaml
rest_command:
  wake_target:
    url: !secret wol_relay_url
    method: POST
    headers:
      X-Auth-Token: !secret wol_relay_token
      Content-Type: application/json
    payload: '{"mac": "AA:BB:CC:DD:EE:FF"}'
    verify_ssl: false
```

Omit `payload` to fall back to `WOL_TARGET_MAC`. The command then becomes
available as the `rest_command.wake_target` action in automations and scripts.

## Unraid

A template is in [unraid/](unraid/): see [README-UNRAID.md](unraid/README-UNRAID.md).

## Logging

One JSON object per line on stdout, so `docker logs` stays greppable and
machine-readable. Time stamps are local time with a UTC offset according to
`TZ` (`Z` for UTC). The auth token is never logged — neither on success nor on
rejection.

```json
{"ts":"2026-01-01T13:00:00.000+01:00","level":"INFO","event":"packet_sent","mac":"aa:bb:cc:dd:ee:ff","broadcast":"255.255.255.255","port":9,"bytes":102,"source":"env"}
{"ts":"2026-01-01T13:00:05.000+01:00","level":"WARNING","event":"auth_rejected","path":"/wol"}
```

## Security notes

- The relay speaks plain HTTP. Keep it on a trusted network segment, or put a
  TLS-terminating reverse proxy in front of it.
- The token is compared in constant time, but there is no rate limiting — a
  reachable relay with a short token is guessable. Use a long random secret.
- Anyone holding the token can wake any MAC address reachable from the host
  unless `WOL_ALLOW_BODY_MAC=false` pins the target.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt pytest
pytest
```

Run it locally without Docker:

```bash
WOL_AUTH_TOKEN=dev-token WOL_TARGET_MAC=aa:bb:cc:dd:ee:ff python app.py
```

## Contributing and security

Changes are listed in [CHANGELOG.md](CHANGELOG.md). Report vulnerabilities
privately, see [SECURITY.md](SECURITY.md).

## License

MIT — see [LICENSE](LICENSE).
