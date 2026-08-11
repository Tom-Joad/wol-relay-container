"""Magic packet construction and delivery.

Kept free of framework and configuration concerns so it can be unit tested
without an HTTP server or environment variables.
"""

from __future__ import annotations

import re
import socket

_MAC_SEPARATORS = re.compile(r"[:\-.\s]")
_HEX_12 = re.compile(r"\A[0-9a-f]{12}\Z")

MAGIC_PACKET_LENGTH = 102


def normalize_mac(value: str) -> str:
    """Return ``value`` as a lowercase colon-separated MAC address.

    Accepts the common spellings (``aa:bb:cc:dd:ee:ff``, ``AA-BB-CC-DD-EE-FF``,
    ``aabb.ccdd.eeff``, ``aabbccddeeff``) and raises ``ValueError`` otherwise.
    """
    if not isinstance(value, str):
        raise ValueError("MAC address must be a string")

    stripped = _MAC_SEPARATORS.sub("", value).lower()
    if not _HEX_12.match(stripped):
        raise ValueError(f"invalid MAC address: {value!r}")

    return ":".join(stripped[i : i + 2] for i in range(0, 12, 2))


def build_magic_packet(mac: str) -> bytes:
    """Build the 102 byte magic packet for an already normalized MAC."""
    payload = bytes.fromhex(mac.replace(":", ""))
    return b"\xff" * 6 + payload * 16


def send_magic_packet(mac: str, broadcast_address: str, port: int) -> int:
    """Broadcast a magic packet for ``mac``; return the number of bytes sent.

    Raises ``OSError`` if the datagram cannot be sent.
    """
    packet = build_magic_packet(mac)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        return sock.sendto(packet, (broadcast_address, port))
