# SPDX-License-Identifier: LGPL-2.1-or-later
"""Numeric, authenticated local IPC needs neither LAN names nor web proxies."""
from http.server import ThreadingHTTPServer
from socketserver import TCPServer
import urllib.request
import urllib.error
from urllib.parse import urlsplit


class LoopbackHTTPServer(ThreadingHTTPServer):
    def server_bind(self):
        if self.server_address[0] != '127.0.0.1':
            raise ValueError('CADWiz IPC must bind numeric IPv4 loopback only')
        # HTTPServer.server_bind resolves a display-only fully qualified name.
        # Keep the actual numeric identity instead; do not consult LAN/DNS.
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


class _LoopbackOnly(urllib.request.BaseHandler):
    handler_order = 0

    def default_open(self, request):
        parsed = urlsplit(request.full_url)
        if (parsed.scheme != 'http' or parsed.hostname != '127.0.0.1'
                or parsed.username is not None or parsed.password is not None
                or parsed.port is None or not 1 <= parsed.port <= 65535):
            raise urllib.error.URLError('CADWiz IPC accepts numeric loopback HTTP endpoints only')
        return None


def opener():
    # These clients address only 127.0.0.1. Do not inherit a system/global
    # proxy or forward a local authentication token through a redirect.
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _LoopbackOnly(), _NoRedirect())
