# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
from integrations.freecad_native.panel_preferences import (
    FreeCADPanelPreferencesStore,
    PanelPreferences,
)


class FakeParameterGroup:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def GetString(self, name: str, default: str) -> str:
        return str(self.values.get(name, default))

    def GetBool(self, name: str, default: bool) -> bool:
        return bool(self.values.get(name, default))

    def GetInt(self, name: str, default: int) -> int:
        return int(self.values.get(name, default))

    def SetString(self, name: str, value: str) -> None:
        self.values[name] = value

    def SetBool(self, name: str, value: bool) -> None:
        self.values[name] = value

    def SetInt(self, name: str, value: int) -> None:
        self.values[name] = value


def test_new_install_defaults_to_find_models_and_remembers_tabs() -> None:
    group = FakeParameterGroup()
    store = FreeCADPanelPreferencesStore(group)
    assert store.load().last_tab_index == 0
    assert store.load().remember_last_tab

    store.save(PanelPreferences(last_tab_index=2))
    assert store.load().last_tab_index == 2


def test_invalid_tab_and_scale_are_safely_bounded() -> None:
    group = FakeParameterGroup()
    group.values.update(LastTabIndex=99, InterfaceScalePercent=500)
    preferences = FreeCADPanelPreferencesStore(group).load()
    assert preferences.last_tab_index == 0
    assert preferences.interface_scale_percent == 160


def test_restore_defaults_does_not_expose_mandatory_safety_switches() -> None:
    fields = PanelPreferences.__dataclass_fields__
    assert "disable_validation" not in fields
    assert "disable_checkpoints" not in fields
    assert "disable_approvals" not in fields
    store = FreeCADPanelPreferencesStore(FakeParameterGroup())
    assert store.restore_defaults() == PanelPreferences()
