"""Magic packet construction and delivery.

Wake-on-LAN only works when the magic packet actually lands on the target's
link, so we shotgun it: every broadcast address the host owns, the limited
broadcast address, the device's own IP (useful while the ARP entry is still
warm) and any operator-supplied broadcast address, on both of the ports that
NICs commonly listen on.
"""

import fcntl
import re
import socket
import struct

SIOCGIFBRDADDR = 0x8919
WOL_PORTS = (9, 7)
_MAC_SEPARATORS = re.compile(r"[:\-.\s]")


def normalize_mac(mac):
    """Return a MAC as ``AA:BB:CC:DD:EE:FF`` or raise ValueError."""
    cleaned = _MAC_SEPARATORS.sub("", str(mac)).upper()
    if len(cleaned) != 12 or any(c not in "0123456789ABCDEF" for c in cleaned):
        raise ValueError("'%s' is not a valid MAC address" % mac)
    return ":".join(cleaned[i:i + 2] for i in range(0, 12, 2))


def magic_packet(mac):
    """Build the 102 byte magic packet: 6x 0xFF then the MAC 16 times."""
    payload = bytes.fromhex(normalize_mac(mac).replace(":", ""))
    return b"\xff" * 6 + payload * 16


def broadcast_addresses():
    """Every IPv4 broadcast address on this host (needs host networking)."""
    found = []
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for _index, name in socket.if_nameindex():
            try:
                packed = fcntl.ioctl(
                    sock.fileno(),
                    SIOCGIFBRDADDR,
                    struct.pack("256s", name[:15].encode()),
                )
            except OSError:
                continue
            address = socket.inet_ntoa(packed[20:24])
            if address in ("0.0.0.0", "255.255.255.255"):
                continue
            if address.startswith("127.") or address in found:
                continue
            found.append(address)
    finally:
        sock.close()
    return found


def wake(mac, broadcast=None, ip=None, repeat=3):
    """Send the magic packet for ``mac`` everywhere it could plausibly help.

    Returns the list of ``"address:port"`` targets that accepted the datagram.
    """
    packet = magic_packet(mac)

    targets = []
    for address in [broadcast] + broadcast_addresses() + ["255.255.255.255", ip]:
        if address and address not in targets:
            targets.append(address)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    delivered = []
    try:
        for address in targets:
            for port in WOL_PORTS:
                try:
                    for _ in range(repeat):
                        sock.sendto(packet, (address, port))
                except OSError:
                    continue
                delivered.append("%s:%d" % (address, port))
    finally:
        sock.close()

    if not delivered:
        raise OSError("could not send the magic packet on any interface")
    return delivered
