"""Is the machine awake yet?

Three probes, cheapest and most reliable first: a TCP connect to a port the
user knows is open, an ICMP echo, then the host ARP cache (which is often the
only thing that answers for a Windows box with its firewall closed).
"""

import re
import socket
import subprocess

ARP_TABLE = "/proc/net/arp"
_EMPTY_MAC = "00:00:00:00:00:00"


def tcp_probe(ip, port, timeout=1.0):
    try:
        with socket.create_connection((ip, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def ping_probe(ip, timeout=1):
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", str(timeout), ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout + 2,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def arp_probe(mac=None, ip=None):
    """Look for a complete ARP entry, which means the NIC answered recently."""
    try:
        with open(ARP_TABLE, "r", encoding="utf-8") as handle:
            rows = handle.read().splitlines()[1:]
    except OSError:
        return False

    mac = (mac or "").upper()
    for row in rows:
        fields = re.split(r"\s+", row.strip())
        if len(fields) < 4:
            continue
        entry_ip, flags, entry_mac = fields[0], fields[2], fields[3].upper()
        if flags == "0x0" or entry_mac == _EMPTY_MAC:
            continue
        if (mac and entry_mac == mac) or (ip and entry_ip == ip):
            return True
    return False


def check(device, timeout=1.0):
    """Return ``{"online": bool, "method": str}`` for a device dict."""
    ip = (device.get("ip") or "").strip()
    port = device.get("port")
    mac = device.get("mac")

    if ip and port:
        if tcp_probe(ip, port, timeout):
            return {"online": True, "method": "tcp/%s" % port}
    if ip:
        if ping_probe(ip, int(timeout) or 1):
            return {"online": True, "method": "ping"}
    if arp_probe(mac, ip):
        return {"online": True, "method": "arp"}
    return {"online": False, "method": "tcp/%s" % port if (ip and port) else ("ping" if ip else "arp")}
