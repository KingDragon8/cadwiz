# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Credential boundaries and conservative diagnostic redaction."""

from __future__ import annotations

import re
from importlib import import_module
from typing import Any, Protocol, cast

_SECRET_FIELDS = {"api_key", "apikey", "token", "secret", "password", "authorization", "credential"}
_SECRET_TEXT = re.compile(
    r"(?i)(sk-[a-z0-9_-]{12,}|bearer\s+[a-z0-9._-]+|"
    r"(?:api[_-]?key|token|secret|password)\s*[:=]\s*[^\s]+)"
)


class CredentialStore(Protocol):
    def set(self, provider: str, secret: str) -> None: ...
    def get(self, provider: str) -> str | None: ...
    def remove(self, provider: str) -> None: ...


class InMemoryCredentialStore:
    """Test-only store. Production setup must use an OS credential store."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def set(self, provider: str, secret: str) -> None:
        if len(secret.strip()) < 12:
            raise ValueError("credential is missing or too short")
        self._values[provider] = secret.strip()

    def get(self, provider: str) -> str | None:
        return self._values.get(provider)

    def remove(self, provider: str) -> None:
        self._values.pop(provider, None)


class KeyringCredentialStore:
    """OS-backed credential storage; refuses insecure plaintext fallback."""

    SERVICE = "CADWiz-AI-Integration"

    @staticmethod
    def _keyring() -> Any:
        try:
            return import_module("keyring")
        except ModuleNotFoundError as error:
            raise RuntimeError("Install keyring before saving provider credentials") from error

    def set(self, provider: str, secret: str) -> None:
        if len(secret.strip()) < 12:
            raise ValueError("credential is missing or too short")
        self._keyring().set_password(self.SERVICE, provider, secret.strip())

    def get(self, provider: str) -> str | None:
        return cast(str | None, self._keyring().get_password(self.SERVICE, provider))

    def remove(self, provider: str) -> None:
        try:
            self._keyring().delete_password(self.SERVICE, provider)
        except Exception:
            return


def redact_diagnostics(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if key.casefold() in _SECRET_FIELDS else redact_diagnostics(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_diagnostics(item) for item in value]
    if isinstance(value, str):
        return _SECRET_TEXT.sub("[REDACTED]", value)
    return value
