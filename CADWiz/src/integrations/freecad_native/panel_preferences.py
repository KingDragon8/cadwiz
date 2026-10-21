# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Safe local preferences for the native CADWiz panel."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any


@dataclass(frozen=True, slots=True)
class PanelPreferences:
    """Non-model UI preferences; mandatory safety behavior is intentionally absent."""

    experience_mode: str = "beginner"
    assistance_mode: str = "do_and_explain"
    spoken_welcome: bool = True
    # Silences synthesis only. The reply is still produced and still shown as
    # text — this is a listening preference, not an offline or no-key mode.
    voice_output: bool = True
    #: Best = live streaming voice (uses tokens); Free = pre-recorded clips
    #: ($0 to run); None = no spoken reply. Named for the trade the user is
    #: making rather than for the technology behind it.
    voice_mode: str = "best"
    #: How the user talks TO CADWiz: "live" is continuous listening, "push" is
    #: hold-to-speak. Stored here because it was previously held only in the
    #: buttons themselves -- it reset to "live" on every launch, and because
    #: Live forces the Best voice, that silently re-disabled Free and None each
    #: time. A user who chose Push to Talk and the Free voice got neither back.
    #:
    #: Not the same thing as `interaction_preference`, which is voice-versus-text
    #: and answers a different question.
    speech_mode: str = "live"
    #: What CADWiz optimises for: automatic, free, private, maximum_quality.
    #: One stored setting, so the AI tab and any other surface that offers this
    #: choice cannot drift apart.
    ai_optimise_for: str = "automatic"
    tooltip_detail: str = "standard"
    # 150, not 100. The panel is read at arm's length on a desktop monitor
    # while the user is looking at a 3D model, not leaned into like a document.
    # Anyone who wants the old size can still drag the slider down to 80.
    interface_scale_percent: int = 150
    remember_last_tab: bool = True
    last_tab_index: int = 0
    show_suggested_actions: bool = True
    explanation_detail: str = "standard"
    show_previews_automatically: bool = True
    interaction_preference: str = "voice_and_text"
    confirmation_behavior: str = "risk_based"
    modification_workflow: str = "protected_from_to"
    default_printer: str = ""
    default_slicer: str = "ELEGOO Cura"
    preferred_materials: str = "PLA, PETG, TPU"
    unit_system: str = "metric"
    ai_assistant_app: str = "codex_chatgpt"


class FreeCADPanelPreferencesStore:
    """Persist appropriate UI preferences in FreeCAD's local parameter store."""

    _PATH = "User parameter:BaseApp/Preferences/AIFreeCAD/Panel"
    # Must match the number of tabs the panel builds. An out-of-range index is
    # clamped to 0 on both save and load, so a stale value here silently loses
    # the last-tab memory for every tab beyond it rather than failing loudly.
    _TAB_COUNT = 7

    def __init__(self, group: Any | None = None) -> None:
        self._provided_group = group

    def _group(self) -> Any:
        if self._provided_group is not None:
            return self._provided_group
        return import_module("FreeCAD").ParamGet(self._PATH)

    def load(self) -> PanelPreferences:
        group = self._group()
        index = group.GetInt("LastTabIndex", 0)
        if not 0 <= index < self._TAB_COUNT:
            index = 0
        scale = min(max(group.GetInt("InterfaceScalePercent", 150), 80), 160)
        return PanelPreferences(
            experience_mode=group.GetString("ExperienceMode", "beginner"),
            assistance_mode=group.GetString("AssistanceMode", "do_and_explain"),
            spoken_welcome=group.GetBool("SpokenWelcome", True),
            voice_output=group.GetBool("VoiceOutput", True),
            speech_mode=group.GetString("SpeechMode", "live"),
            ai_optimise_for=group.GetString("AIOptimiseFor", "automatic"),
            voice_mode=group.GetString("VoiceMode", "best"),
            tooltip_detail=group.GetString("TooltipDetail", "standard"),
            interface_scale_percent=scale,
            remember_last_tab=group.GetBool("RememberLastTab", True),
            last_tab_index=index,
            show_suggested_actions=group.GetBool("ShowSuggestedActions", True),
            explanation_detail=group.GetString("ExplanationDetail", "standard"),
            show_previews_automatically=group.GetBool("ShowPreviewsAutomatically", True),
            interaction_preference=group.GetString(
                "InteractionPreference", "voice_and_text"
            ),
            confirmation_behavior=group.GetString(
                "ConfirmationBehavior", "risk_based"
            ),
            modification_workflow=group.GetString(
                "ModificationWorkflow", "protected_from_to"
            ),
            default_printer=group.GetString("DefaultPrinter", ""),
            default_slicer=group.GetString("DefaultSlicer", "ELEGOO Cura"),
            preferred_materials=group.GetString(
                "PreferredMaterials", "PLA, PETG, TPU"
            ),
            unit_system=group.GetString("UnitSystem", "metric"),
            ai_assistant_app=group.GetString("AIAssistantApp", "codex_chatgpt"),
        )

    def save(self, preferences: PanelPreferences) -> None:
        group = self._group()
        group.SetString("ExperienceMode", preferences.experience_mode)
        group.SetString("AssistanceMode", preferences.assistance_mode)
        group.SetBool("SpokenWelcome", preferences.spoken_welcome)
        group.SetBool("VoiceOutput", preferences.voice_output)
        group.SetString("VoiceMode", preferences.voice_mode)
        group.SetString("SpeechMode", preferences.speech_mode)
        group.SetString("AIOptimiseFor", preferences.ai_optimise_for)
        group.SetString("TooltipDetail", preferences.tooltip_detail)
        group.SetInt(
            "InterfaceScalePercent",
            min(max(preferences.interface_scale_percent, 80), 160),
        )
        group.SetBool("RememberLastTab", preferences.remember_last_tab)
        group.SetInt(
            "LastTabIndex",
            preferences.last_tab_index if 0 <= preferences.last_tab_index < self._TAB_COUNT else 0,
        )
        group.SetBool("ShowSuggestedActions", preferences.show_suggested_actions)
        group.SetString("ExplanationDetail", preferences.explanation_detail)
        group.SetBool("ShowPreviewsAutomatically", preferences.show_previews_automatically)
        group.SetString("InteractionPreference", preferences.interaction_preference)
        group.SetString("ConfirmationBehavior", preferences.confirmation_behavior)
        group.SetString("ModificationWorkflow", preferences.modification_workflow)
        group.SetString("DefaultPrinter", preferences.default_printer)
        group.SetString("DefaultSlicer", preferences.default_slicer)
        group.SetString("PreferredMaterials", preferences.preferred_materials)
        group.SetString("UnitSystem", preferences.unit_system)
        group.SetString("AIAssistantApp", preferences.ai_assistant_app)

    def restore_defaults(self) -> PanelPreferences:
        defaults = PanelPreferences()
        self.save(defaults)
        return defaults
