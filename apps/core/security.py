"""Trust client address headers only when the immediate peer is an approved proxy."""
from ipaddress import ip_address, ip_network

from django.conf import settings


def client_ip(request):
    try:
        peer = ip_address(request.META.get("REMOTE_ADDR", ""))
    except ValueError:
        return None
    networks = [ip_network(value) for value in settings.TRUSTED_PROXY_CIDRS]
    if any(peer in network for network in networks):
        addresses = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")
        for value in reversed(addresses):
            try:
                address = ip_address(value.strip())
            except ValueError:
                return str(peer)
            if not any(address in network for network in networks):
                return str(address)
    return str(peer)
