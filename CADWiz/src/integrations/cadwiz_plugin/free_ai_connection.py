# SPDX-License-Identifier: LGPL-2.1-or-later
"""User-initiated Groq account handshake; no inference or project transmission.

This is enrollment, not CAD qualification. Windows Credential Manager stores
the key. No paid route, caller-supplied URL, redirects or model code execution.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


class ConnectionFailure(RuntimeError):
    pass


class WindowsCredentialStore:
    """Current user's OS credential vault. No plaintext fallback on any platform."""

    def __init__(self, target: str = "CADWiz/FreeAI/Groq") -> None:
        if sys.platform != "win32":
            raise ConnectionFailure("Secure credential enrollment is currently supported on Windows only.")
        self.target = target

    @staticmethod
    def _api():
        class Credential(ctypes.Structure):
            _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
                        ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
                        ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
                        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)), ("Persist", wintypes.DWORD),
                        ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                        ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]
        dll = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        dll.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
        dll.CredWriteW.restype = wintypes.BOOL
        dll.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                 ctypes.POINTER(ctypes.POINTER(Credential))]
        dll.CredReadW.restype = wintypes.BOOL
        dll.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        dll.CredDeleteW.restype = wintypes.BOOL
        dll.CredFree.argtypes = [ctypes.c_void_p]
        return dll, Credential

    def set(self, secret: str) -> None:
        secret = validate_key(secret)
        dll, kind = self._api()
        raw = secret.encode("utf-8")
        blob = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
        record = kind(Type=1, TargetName=self.target, CredentialBlobSize=len(raw),
                      CredentialBlob=blob, Persist=2, UserName="CADWiz")
        if not dll.CredWriteW(ctypes.byref(record), 0):
            raise ConnectionFailure("Windows could not save the credential. Nothing was written to a settings file.")

    def get(self) -> str | None:
        dll, kind = self._api()
        pointer = ctypes.POINTER(kind)()
        if not dll.CredReadW(self.target, 1, 0, ctypes.byref(pointer)):
            if ctypes.get_last_error() == 1168:
                return None
            raise ConnectionFailure("Windows credential storage could not be read.")
        try:
            return ctypes.string_at(pointer.contents.CredentialBlob,
                                    pointer.contents.CredentialBlobSize).decode("utf-8")
        finally:
            dll.CredFree(pointer)

    def remove(self) -> None:
        dll, _ = self._api()
        if not dll.CredDeleteW(self.target, 1, 0) and ctypes.get_last_error() != 1168:
            raise ConnectionFailure("Windows could not remove the saved credential.")


def validate_key(value: str) -> str:
    if not isinstance(value, str):
        raise ConnectionFailure("Enter your API key in the masked field.")
    value = value.strip()
    if not 16 <= len(value) <= 512 or not value.isascii() or any(c.isspace() for c in value):
        raise ConnectionFailure("The API key format is invalid. Check it in your provider console.")
    return value


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def check_provider_key(provider: str, secret: str, *, consent: bool = False, opener=None) -> dict:
    """Fixed-host read-only authentication check; never an inference request."""
    from .free_ai_manager import CATALOG
    if provider not in CATALOG:
        raise ConnectionFailure("Choose a supported provider.")
    guide = CATALOG[provider]
    if consent is not True:
        raise ConnectionFailure("Allow the provider connection check before any credential is sent.")
    secret = validate_key(secret)
    request = Request(guide.models_url,
                      headers={guide.auth_header: guide.auth_prefix + secret, "Accept": "application/json",
                               "User-Agent": "CADWiz-Free-AI-Beta"}, method="GET")
    client = opener if opener is not None else build_opener(_NoRedirect())
    try:
        with client.open(request, timeout=15) as response:
            data = response.read(1024 * 1024 + 1)
            if len(data) > 1024 * 1024:
                raise ConnectionFailure("The provider returned an oversized reply. Connection not accepted.")
    except HTTPError as error:
        messages = {401: "The provider rejected the key. Check or replace it in your provider console.",
                    403: "The account is not permitted to use this API. Review its region and permissions.",
                    429: "The provider is rate-limiting this account. Wait and try again; no automatic retry was made."}
        raise ConnectionFailure(messages.get(error.code, "The provider could not verify this connection. No fallback or paid request was made.")) from None
    except (URLError, TimeoutError, OSError):
        raise ConnectionFailure("The provider could not be reached. Check your connection and try again.") from None
    try:
        parsed = json.loads(data)
        count = None
        if guide.response_list == 'key':
            if not isinstance(parsed.get('data'),dict):raise ValueError
        elif guide.response_list == 'token':
            if parsed.get('success') is not True or parsed.get('result',{}).get('status')!='active':raise ValueError
        elif guide.response_list == 'github':
            if not isinstance(parsed.get('id'),int):raise ValueError
        else:
            models=parsed[guide.response_list]
            if not isinstance(models,list) or not models or not all(isinstance(m,dict) and isinstance(m.get('id',m.get('name')),str)for m in models):raise ValueError
            count=len(models)
    except (ValueError, KeyError, TypeError):
        raise ConnectionFailure("The provider returned an unexpected reply. Connection not accepted.") from None
    # Neither IDs nor model descriptions become executable instructions or logs.
    return {"provider": guide.name, "provider_id": provider, "connection_verified": True, "available_model_count": count,
            "cad_qualified": False, "billing_verified": False, "remaining_capacity": "Unknown",
            "message": "API connection verified. Free billing eligibility and CAD benchmarks still need verification."}


def check_groq_key(secret: str, *, consent: bool = False, opener=None) -> dict:
    return check_provider_key('groq',secret,consent=consent,opener=opener)
