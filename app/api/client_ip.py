"""The client address for unauthenticated rate limits (M7 review, HIGH-1).

The socket peer, unless the peer is a trusted proxy (TRUSTED_PROXIES): then the rightmost
X-Forwarded-For hop that isn't itself trusted. Anything else in that header is ignored,
so a client can't pick its own bucket by sending the header.
"""

from collections.abc import Sequence
from ipaddress import IPv4Network, IPv6Network, ip_address

Network = IPv4Network | IPv6Network


def _trusted(address: str, trusted: Sequence[Network]) -> bool:
    try:
        ip = ip_address(address)
    except ValueError:
        return False
    return any(ip in network for network in trusted)


def client_ip(
    peer: str | None, forwarded_for: str | None, trusted: Sequence[Network]
) -> str:
    if peer is None:
        return "unknown"
    if not forwarded_for or not _trusted(peer, trusted):
        return peer
    hops = []
    for part in forwarded_for.split(","):
        try:
            hops.append(str(ip_address(part.strip())))
        except ValueError:
            continue  # malformed entries are never a client identity
    for hop in reversed(hops):
        if not _trusted(hop, trusted):
            return hop
    return hops[0] if hops else peer
