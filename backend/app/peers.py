"""Resolve the client address for the shared verification quota."""
from ipaddress import ip_address, ip_network
import os


def quota_peer(peer, forwarded):
    try:
        address = ip_address(peer)
        trusted = [ip_network(value.strip()) for value in os.getenv("TRUSTED_PROXY_CIDRS", "").split(",") if value.strip()]
    except ValueError:
        return peer
    for item in reversed((forwarded or "").split(",")):
        if not any(address in network for network in trusted):
            break
        try:
            address = ip_address(item.strip())
        except ValueError:
            return peer
    return str(address)
