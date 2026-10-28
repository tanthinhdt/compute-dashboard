"""Explicit IP allowlist; forwarded headers are trusted only when configured."""
import html
import ipaddress

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import HTMLResponse, JSONResponse


class IPAccessMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, allowed_networks, trusted_proxies=None, enabled=True):
        super().__init__(app)
        self.enabled = enabled
        self.networks = [ipaddress.ip_network(net, strict=False) for net in allowed_networks]
        self.trusted_proxies = set(trusted_proxies or [])

    def get_client_ip(self, request):
        peer = request.client.host if request.client else ''
        if peer not in self.trusted_proxies:
            return peer
        # Walk from the trusted peer toward the client; never blindly accept
        # the leftmost value supplied by an untrusted upstream client.
        chain = [value.strip() for value in request.headers.get('x-forwarded-for', '').split(',') if value.strip()]
        for value in reversed(chain):
            if peer not in self.trusted_proxies:
                break
            peer = value
        return peer

    def is_ip_allowed(self, value):
        if not self.enabled:
            return True
        try:
            address = ipaddress.ip_address(value)
            return any(address in network for network in self.networks)
        except ValueError:
            return False

    async def dispatch(self, request, call_next):
        address = self.get_client_ip(request)
        request.state.client_ip = address
        request.state.is_allowed = self.is_ip_allowed(address)
        if request.state.is_allowed:
            return await call_next(request)
        if request.url.path.startswith('/api/'):
            return JSONResponse({'error': 'Forbidden', 'message': 'Network access denied'}, status_code=403)
        return HTMLResponse('<h1>Access restricted</h1><p>Connect from an authorized network.</p>'
                            + '<p>Client: ' + html.escape(address) + '</p>', status_code=403)
