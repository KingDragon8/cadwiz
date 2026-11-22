# SPDX-License-Identifier: LGPL-2.1-or-later
"""OS vault adapters. No plaintext fallback, secret command arguments or logs."""
from __future__ import annotations

import ctypes
import shutil
import subprocess
import sys

from .free_ai_connection import ConnectionFailure, WindowsCredentialStore, validate_key
from .free_ai_manager import CATALOG


class MacCredentialStore:
    """Login Keychain, using Security.framework directly (including Monterey)."""
    def __init__(self, provider: str):
        self.service = b"CADWiz/FreeAI"
        self.account = provider.encode("ascii")
        try:
            self.api = ctypes.CDLL("/System/Library/Frameworks/Security.framework/Security")
            self.cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
            self.api.SecKeychainFindGenericPassword.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p,
                ctypes.c_uint32, ctypes.c_char_p, ctypes.POINTER(ctypes.c_uint32),
                ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)]
            self.api.SecKeychainAddGenericPassword.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p,
                ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p]
            self.api.SecKeychainItemModifyAttributesAndData.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                ctypes.c_uint32, ctypes.c_void_p]
            self.api.SecKeychainItemDelete.argtypes = [ctypes.c_void_p]
            self.api.SecKeychainItemFreeContent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            self.cf.CFRelease.argtypes = [ctypes.c_void_p]
            for name in ("SecKeychainFindGenericPassword", "SecKeychainAddGenericPassword",
                         "SecKeychainItemModifyAttributesAndData", "SecKeychainItemDelete"):
                getattr(self.api, name).restype = ctypes.c_int32
        except (OSError, AttributeError):
            raise ConnectionFailure("macOS Keychain is unavailable. Unlock your login keychain and try again; no key was saved.") from None

    def _find(self):
        size, data, item = ctypes.c_uint32(), ctypes.c_void_p(), ctypes.c_void_p()
        result = self.api.SecKeychainFindGenericPassword(None, len(self.service), self.service,
            len(self.account), self.account, ctypes.byref(size), ctypes.byref(data), ctypes.byref(item))
        if result == -25300:  # errSecItemNotFound
            return None, None
        if result:
            raise ConnectionFailure("Keychain access failed. Unlock your login keychain and approve CADWiz access locally.")
        try:
            value = ctypes.string_at(data, size.value).decode("utf-8")
        except (ValueError, UnicodeError):
            if item.value:
                self.cf.CFRelease(item)
            raise ConnectionFailure("The stored Keychain credential could not be read. Re-enter it locally.") from None
        finally:
            self.api.SecKeychainItemFreeContent(None, data)
        return value, item

    def get(self):
        value, item = self._find()
        if item is not None:
            self.cf.CFRelease(item)
        return value

    def set(self, secret):
        raw = validate_key(secret).encode("utf-8")
        _old, item = self._find()
        try:
            if item is None:
                status = self.api.SecKeychainAddGenericPassword(None, len(self.service), self.service,
                    len(self.account), self.account, len(raw), raw, None)
            else:
                status = self.api.SecKeychainItemModifyAttributesAndData(item, None, len(raw), raw)
            if status:
                raise ConnectionFailure("Keychain could not save the key. Unlock your login keychain and try again.")
        finally:
            if item is not None:
                self.cf.CFRelease(item)

    def remove(self):
        _value, item = self._find()
        if item is not None:
            try:
                if self.api.SecKeychainItemDelete(item):
                    raise ConnectionFailure("Keychain could not remove this credential. Check local Keychain access.")
            finally:
                self.cf.CFRelease(item)


class LinuxCredentialStore:
    """Secret Service through libsecret's CLI; secrets only travel over pipes."""
    def __init__(self, provider: str, *, executable=None, runner=subprocess.run):
        self.executable = executable or shutil.which("secret-tool")
        self.provider, self.runner = provider, runner
        if not self.executable:
            raise ConnectionFailure("Secure storage is unavailable. Install libsecret-tools and unlock a Secret Service keyring (such as GNOME Keyring). No plaintext fallback is used.")

    def _run(self, action, secret=None):
        args = [self.executable, action]
        if action == "store":
            args += ["--label=CADWiz API credential"]
        args += ["service", "CADWiz/FreeAI", "account", self.provider]
        try:
            result = self.runner(args, input=secret, text=True, capture_output=True,
                                 timeout=20, check=False)
        except (OSError, subprocess.SubprocessError):
            raise ConnectionFailure("Secret Service is unavailable or locked. Start your desktop keyring service, unlock it, and retry.") from None
        if result.returncode:
            # lookup exit 1 without stderr means the requested item does not exist.
            if action in ("lookup", "clear") and result.returncode == 1 and not result.stderr.strip():
                return None
            raise ConnectionFailure("Secret Service could not complete this operation. Unlock your desktop keyring and retry; no settings-file fallback was used.")
        return result.stdout.rstrip("\r\n")

    def get(self):
        return self._run("lookup")

    def set(self, secret):
        self._run("store", validate_key(secret))

    def remove(self):
        self._run("clear")


def credential_store(provider="groq", *, platform=None):
    if provider not in CATALOG:
        raise ConnectionFailure("Choose a supported provider before opening credential storage.")
    platform = platform or sys.platform
    if platform == "win32":
        # Preserve the existing Windows key identifiers; never migrate via plaintext.
        return WindowsCredentialStore("CADWiz/FreeAI/" + ("Groq" if provider == "groq" else provider))
    if platform == "darwin":
        return MacCredentialStore(provider)
    if platform.startswith("linux"):
        return LinuxCredentialStore(provider)
    raise ConnectionFailure("This operating system has no supported secure credential vault. No key was saved.")
