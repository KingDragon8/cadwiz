# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Public contracts for native CAD-host adapters."""

from .contracts import (
    AdapterCapability,
    CompatibilityReport,
    DependencyState,
    GuiThreadDispatcher,
    NativeAdapterError,
    NativeErrorCode,
    NativeEventSubscription,
    NativeFreeCADReadAdapter,
    NativeObjectState,
    PropertyValue,
)

__all__ = (
    "AdapterCapability",
    "CompatibilityReport",
    "DependencyState",
    "GuiThreadDispatcher",
    "NativeAdapterError",
    "NativeErrorCode",
    "NativeEventSubscription",
    "NativeFreeCADReadAdapter",
    "NativeObjectState",
    "PropertyValue",
)
