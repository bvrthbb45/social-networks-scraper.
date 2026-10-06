"""Request rate limiting (per client address).

The counters live in process memory: correct for the single API instance this system runs as. If
it is ever scaled out, switch the limiter to a shared (Redis) storage URI. Behind the reverse proxy
the API is started with ``--proxy-headers`` so ``request.client`` is the real caller.
"""

from slowapi import Limiter
from starlette.requests import Request


def client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


limiter = Limiter(key_func=client_key)
