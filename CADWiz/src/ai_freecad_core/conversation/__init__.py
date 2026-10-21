# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Durable, host-neutral CADWiz conversation and feedback services."""

from importlib import import_module as _import_module

#: name -> (submodule, attribute). Loaded on first use, so importing one submodule
#: (say `.audit`) does not load the whole package (ORDER-2026-10-21-01: keeps the
#: model-routing code out of the Claude plug-in, which only needs the audit log).
_LAZY = {
    'Attachment': ('contracts', 'Attachment'),
    'AttachmentKind': ('contracts', 'AttachmentKind'),
    'ConversationMessage': ('contracts', 'ConversationMessage'),
    'FeedbackCategory': ('contracts', 'FeedbackCategory'),
    'FeedbackDraft': ('contracts', 'FeedbackDraft'),
    'FeedbackStatus': ('contracts', 'FeedbackStatus'),
    'MessageRole': ('contracts', 'MessageRole'),
    'VoiceState': ('contracts', 'VoiceState'),
    'ConversationIntegrityAuditor': ('integrity', 'ConversationIntegrityAuditor'),
    'DesignIntentRecord': ('integrity', 'DesignIntentRecord'),
    'FailureClass': ('integrity', 'FailureClass'),
    'KnownFact': ('integrity', 'KnownFact'),
    'OperationRecord': ('integrity', 'OperationRecord'),
    'OperationState': ('integrity', 'OperationState'),
    'RepairRecord': ('integrity', 'RepairRecord'),
    'ConversationService': ('service', 'ConversationService'),
    'FeedbackReceipt': ('service', 'FeedbackReceipt'),
    'ConversationStore': ('store', 'ConversationStore'),
}


def __getattr__(name: str):
    try:
        module, attribute = _LAZY[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    value = getattr(_import_module(f".{module}", __name__), attribute)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY))

__all__ = [
    "Attachment",
    "AttachmentKind",
    "ConversationMessage",
    "ConversationService",
    "ConversationStore",
    "ConversationIntegrityAuditor",
    "DesignIntentRecord",
    "FailureClass",
    "KnownFact",
    "OperationRecord",
    "OperationState",
    "RepairRecord",
    "FeedbackCategory",
    "FeedbackDraft",
    "FeedbackReceipt",
    "FeedbackStatus",
    "MessageRole",
    "VoiceState",
]
