"""Shared slowapi limiter.

Lives in its own module so routes and ``main`` can import the same limiter
instance without a circular import.

The key is the client address as uvicorn reports it. Behind a reverse proxy
that is the proxy's own address — one bucket shared by every client, so a
single client hammering the login locks everyone out — unless the proxy's
address is listed in FORWARDED_ALLOW_IPS, in which case uvicorn takes the
client from X-Forwarded-For. deploy/https/caddy.yml sets that up; see README
"Exposing the server".
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
