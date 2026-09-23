"""HTTPS delivery with connection-time IP pinning, no redirects, bounded reads."""
import hashlib
import hmac
import http.client
import ipaddress
import json
import socket
import ssl
from urllib.parse import urlsplit
from fastapi import HTTPException


def public_address(url):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or parsed.port not in {None, 443}:
        raise HTTPException(422, "Webhook URL requires HTTPS on port 443 without credentials or fragments")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise HTTPException(422, "Webhook hostname cannot be resolved")
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise HTTPException(422, "Webhook destination must resolve exclusively to public addresses")
    return parsed, addresses[0][4][0]


def signature(secret: str, timestamp: str, payload: bytes) -> str:
    return hmac.new(secret.encode(), timestamp.encode() + b"." + payload, hashlib.sha256).hexdigest()


def deliver(url: str, body: bytes, headers: dict) -> int:
    parsed, address = public_address(url)
    class PinnedHTTPS(http.client.HTTPSConnection):
        def connect(self):
            raw = socket.create_connection((address, 443), timeout=5)
            self.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=parsed.hostname)
            self.sock.settimeout(5)
    connection = PinnedHTTPS(parsed.hostname, timeout=5)
    try:
        connection.request("POST", parsed.path or "/" + ("?" + parsed.query if parsed.query else ""), body, headers)
        response = connection.getresponse()
        response.read(2048)
        return response.status
    finally:
        connection.close()
