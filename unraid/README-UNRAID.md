# Running wol-relay-container on Unraid

The container runs permanently, uses host networking and has no web
interface; everything it does shows up in the container log.

## Install

1. **Add the template.** Copy `wol-relay-container.xml` to
   `/boot/config/plugins/dockerMan/templates-user/` on the flash drive. Then,
   in the Unraid web UI, go to **Docker → Add Container** and pick
   `wol-relay-container` from the template dropdown.

2. **Fill in the settings.**

   | Setting | Value |
   |---|---|
   | `WOL_AUTH_TOKEN` | a long random secret, e.g. from `openssl rand -hex 32` |
   | `WOL_TARGET_MAC` | MAC address of the machine to wake (optional if callers send one) |
   | `WOL_LISTEN_PORT` | `8099`; with host networking this port opens on the Unraid host |
   | `PUID`, `PGID` | `99`, `100` (nobody:users) |
   | `TZ` | e.g. `Europe/Berlin` |

   The advanced view has the remaining settings. Don't add `--user` to
   *Extra Parameters*: the container sets the user from `PUID`/`PGID` itself.

3. **Apply.** The log shows `starting` and `Serving on http://0.0.0.0:8099`.

The Unraid host has to sit in the same layer 2 segment as the machine to be
woken, because the magic packet is a broadcast.

## Use

```bash
curl -sS -X POST http://UNRAID_IP:8099/wol -H "X-Auth-Token: YOUR_SECRET"
```

For Home Assistant and the request format see the [main README](../README.md).
