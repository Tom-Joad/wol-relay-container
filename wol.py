"""Magic packet construction and delivery.

Kept free of framework and configuration concerns so it can be unit tested
without an HTTP server or environment variables.
"""

from __future__ import annotations

import re
import socket

# The documented spellings only: six pairs joined by ":" or "-" (one kind
# throughout), three groups of four joined by ".", or twelve digits.
_MAC_FORMATS = re.compile(
    r"\A(?:[0-9a-f]{2}([:-])(?:[0-9a-f]{2}\1){4}[0-9a-f]{2}"
    r"|[0-9a-f]{4}\.[0-9a-f]{4}\.[0-9a-f]{4}"
    r"|[0-9a-f]{12})\Z",
    re.IGNORECASE,
)

MAGIC_PACKET_LENGTH = 102


def normalize_mac(value: str) -> str:
    """Return ``value`` as a lowercase colon-separated MAC address.

    Accepts the common spellings (``aa:bb:cc:dd:ee:ff``, ``AA-BB-CC-DD-EE-FF``,
    ``aabb.ccdd.eeff``, ``aabbccddeeff``) and raises ``ValueError`` otherwise.
    """
    if not isinstance(value, str):
        raise ValueError("MAC address must be a string")

    if not _MAC_FORMATS.match(value.strip()):
        raise ValueError(f"invalid MAC address: {value!r}")

    digits = re.sub(r"[:.-]", "", value.strip()).lower()
    return ":".join(digits[i : i + 2] for i in range(0, 12, 2))


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
