# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""What may reach the founder (ORDER-2026-10-12-04 and its addendum).

Every reply shown or spoken to the founder passes through `clean_reply`. It removes,
sentence by sentence, the things founder rulings forbid:

  * saying CADWiz cannot change his file, or telling him to make an edit himself;
  * saying it cannot search the internet (the master always can);
  * any mode wording (Tutor / Mentor / Wizard mode -- there is one mode now);
  * raw internal error text and parameter lists ("missing coupon parameters:
    overall_width_mm, ..."), which become ONE plain sentence.

Asking him to measure something the model holds is handled where the model is
open (`integrations.freecad_native.measurements.without_measure_requests`), which
can replace the question with the measured answer.

`findings` names what a text would have broken; the test suite fails on any
reply fixture that still has one after cleaning.
"""
from __future__ import annotations

import re

#: The one plain sentence that replaces internal error text.
PLAIN_ERROR = "Something inside CADWiz went wrong on that step, so I stopped it there; nothing of yours was lost."

#: Sentences; a decimal point ("1.6 mm") does not end one.
_SENTENCES = re.compile(r"(?:[^.!?\n]|\.(?=\d))+[.!?]?\s*|\n")

_CANNOT_EDIT = re.compile(
    r"\b(i|cadwiz|wiz)?\s*(can(?:no|['’])?t|can not|am unable to|unable to|am not able to|not able to|don['’]t have the ability to|have no way to)\b"
    r"[^.!?\n]*\b(edit|change|modify|alter|adjust|make (the )?change|update|resize|reshape)\w*\b", re.I)
_DO_IT_YOURSELF = re.compile(
    r"(\byou(?:['’]ll| will)? (?:need to|have to|can|could|should|may want to|might want to) (?:select|open|use|click|edit|change|modify|apply|"
    r"offset|scale|pad|pocket|sketch|redraw|rebuild|measure|check|enter|type|drag)\b"
    r"|\b(?:in freecad|in the (?:part|partdesign|sketcher) workbench),? (?:select|use|open|click|go to)\b"
    r"|\bselect the [^.!?\n]*\b(?:edge|face|sketch|feature)\b[^.!?\n]*\b(?:and|then) (?:check|read|look at|use)\b"
    r"|\bfollow these steps\b|\bhere(?:['’]s| is) how (?:you can|to do it yourself)\b)", re.I)
_CANNOT_SEARCH = re.compile(
    r"\b(can(?:no|['’])?t|can not|unable to|not able to|don['’]t|do not|have no)\b[^.!?\n]*\b(search|browse|look up|access|reach|go on|use)\b"
    r"[^.!?\n]*\b(internet|web|online|websites?)\b"
    r"|\bno (?:internet|web) access\b|\b(?:i )?don['’]t have (?:internet|web) access\b", re.I)
_MODE_WORDS = re.compile(r"\b(tutor|mentor|wizard|teacher)\s+mode\b|\bswitch(?:ed)? to (?:the )?(tutor|mentor|wizard|teacher)\b", re.I)

_RAW_ERROR = re.compile(
    r"Traceback \(most recent call last\)|\b[A-Z][A-Za-z]*(?:Error|Exception)\b\s*:|\bmissing [a-z ]*parameters?\s*:"
    r"|\b(?:KeyError|ValueError|TypeError|AttributeError|RuntimeError|OSError)\b|\bline \d+, in\b|\bFile \"[^\"]+\", line\b"
    r"|\bexit code -?\d+\b|\bstderr\b|\b0x[0-9a-f]{6,}\b", re.I)
_IDENTIFIER = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")


def _parameter_list(sentence: str) -> bool:
    return len(_IDENTIFIER.findall(sentence)) >= 2


def _humanize_identifiers(sentence: str) -> str:
    def word(match: re.Match[str]) -> str:
        parts = match.group(0).split("_")
        if parts[-1] in ("mm", "in", "deg", "mm3", "mm2") and len(parts) > 1:
            parts = parts[:-1]
        return " ".join(parts)

    return _IDENTIFIER.sub(word, sentence)


def findings(text: str) -> list[str]:
    """Each rule this text breaks (empty: safe to show the founder)."""
    found = []
    for name, pattern in (("cannot-edit", _CANNOT_EDIT), ("do-it-yourself", _DO_IT_YOURSELF), ("cannot-search", _CANNOT_SEARCH),
                          ("mode-wording", _MODE_WORDS), ("raw-error", _RAW_ERROR)):
        if pattern.search(text or ""):
            found.append(name)
    if any(_parameter_list(s) for s in _SENTENCES.findall(text or "")):
        found.append("parameter-list")
    return found


def clean_reply(text: str) -> str:
    """The reply with every forbidden sentence removed; internal error text and
    parameter lists become one plain sentence. Empty in, empty out."""
    if not text or not text.strip():
        return text
    if _RAW_ERROR.search(text):
        kept = [s for s in _SENTENCES.findall(text) if s.strip() and not _RAW_ERROR.search(s) and not _parameter_list(s)]
        rest = clean_reply("".join(kept)).strip() if kept else ""
        return (PLAIN_ERROR + (" " + rest if rest else "")).strip()
    out: list[str] = []
    replaced_error = False
    for sentence in _SENTENCES.findall(text):
        if not sentence.strip():
            out.append(sentence)
            continue
        if _CANNOT_EDIT.search(sentence) or _DO_IT_YOURSELF.search(sentence) or _CANNOT_SEARCH.search(sentence) or _MODE_WORDS.search(sentence):
            continue
        if _parameter_list(sentence):
            if re.search(r"\b(missing|invalid|error|failed|unknown|required|not found)\b", sentence, re.I):
                if not replaced_error:
                    out.append(PLAIN_ERROR + " ")
                    replaced_error = True
                continue
        if "http" not in sentence and "\\" not in sentence and "/" not in sentence:
            sentence = _humanize_identifiers(sentence)
        out.append(sentence)
    cleaned = re.sub(r"[ \t]{2,}", " ", "".join(out)).strip()
    return cleaned
