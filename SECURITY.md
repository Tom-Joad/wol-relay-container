# Security policy

## Supported versions

Only the latest release receives fixes. Security fixes go into a new
release of the current major version.

## Reporting a vulnerability

Please do **not** open a public issue for security problems. Report them
privately through GitHub instead: on the
[Security tab](https://github.com/Tom-Joad/wol-relay-container/security),
choose **Report a vulnerability**. You will get an answer within a few days.

## Scope notes

The relay holds a shared secret and can wake any host on its network segment,
so the following are of particular interest:

- the auth token ending up in logs or responses
- a way to send a packet without a valid `X-Auth-Token`
- a way around `WOL_ALLOW_BODY_MAC=false`

The relay speaks plain HTTP and has no rate limiting; see *Security notes* in
the README. The container starts as root only to switch to `PUID:PGID` and
runs the relay as that unprivileged user, with all capabilities dropped but
`SETUID` and `SETGID`.

## Supply chain

Images are built by GitHub Actions. Third-party actions are pinned to commit
SHAs. Dependencies are checked with `pip-audit`, and the repository is scanned
with `gitleaks`. Images are scanned with Trivy and signed keylessly with
cosign. To verify an image:

```bash
cosign verify ghcr.io/tom-joad/wol-relay-container:latest \
  --certificate-identity-regexp 'https://github.com/Tom-Joad/wol-relay-container/' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```
