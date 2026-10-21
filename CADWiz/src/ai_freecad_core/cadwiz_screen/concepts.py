# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""The concept stage before any 3D (ORDER-2026-10-18-02 A).

Claude posts up to three option cards to the founder's screen ("Choosing a
design"): a picture, where it came from, its licence, and whether a 3D file
exists. He picks one, asks for changes (bone instead of stick) and sees a new
round of pictures; every round is kept, like the version slider. Nothing turns
into 3D until he presses "Make it 3D" (or tells Claude to): the founder's own
rule, so he can iterate on pictures first.

Honest about what the pictures are: a card is either a design FOUND somewhere
(with its source and licence) or Claude's own rough SKETCH. Claude does not
generate photo-real images; that is left out until the founder decides on a
paid image generator.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

from .licences import read_licence

MAX_CARDS = 3
HONEST_LINE = ("Claude finds real designs and draws rough sketches; it does not make photo-real pictures. "
               "Nothing becomes 3D until you press Make it 3D.")


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass(slots=True)
class ConceptCard:
    title: str
    picture: str                      # a local file the panel shows
    kind: str = "found"               # "found" (a real design) or "sketch" (Claude's own drawing)
    source: str = ""                  # page or site it came from; "" for a sketch
    licence: str = ""
    has_3d_file: bool = False
    model_url: str = ""
    note: str = ""

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("every card needs a short title")
        if self.kind not in ("found", "sketch"):
            raise ValueError("a card is 'found' (a real design, with its source) or 'sketch' (Claude's own drawing)")
        if self.kind == "found" and not self.source.strip():
            raise ValueError("a found design needs its source (the page it came from)")

    def licence_line(self) -> str:
        if self.kind == "sketch":
            return "Claude's own sketch -- yours to use"
        return read_licence(self.licence).plain

    def three_d_line(self) -> str:
        if self.has_3d_file:
            return "3D file: yes" + (f" ({self.model_url})" if self.model_url else "")
        return "3D file: no -- Claude would model it"

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "licence_line": self.licence_line(), "three_d_line": self.three_d_line(),
                "can_sell": None if self.kind == "sketch" else read_licence(self.licence).can_sell}


@dataclass(slots=True)
class ConceptRound:
    number: int
    cards: list[ConceptCard]
    note: str = ""                     # Claude's words: what this round shows or changed
    utc: str = field(default_factory=_utc)
    picked: int | None = None          # 1-based card number
    picked_utc: str = ""

    def __post_init__(self) -> None:
        if not 1 <= len(self.cards) <= MAX_CARDS:
            raise ValueError(f"a round shows one to {MAX_CARDS} cards")

    def to_dict(self) -> dict[str, Any]:
        return {"round": self.number, "note": self.note, "utc": self.utc, "picked": self.picked, "picked_utc": self.picked_utc,
                "cards": [c.to_dict() for c in self.cards]}


@dataclass(slots=True)
class ConceptHistory:
    """Every round of pictures for one design, oldest first."""

    rounds: list[ConceptRound] = field(default_factory=list)
    make_3d: dict[str, Any] | None = None       # {"round": n, "card": k, "utc": ...} once he presses Make it 3D

    def add_round(self, cards: list[ConceptCard], note: str = "") -> ConceptRound:
        round_ = ConceptRound(len(self.rounds) + 1, list(cards), note)
        self.rounds.append(round_)
        self.make_3d = None                    # a new round is a new choice
        return round_

    @property
    def current(self) -> ConceptRound | None:
        return self.rounds[-1] if self.rounds else None

    def pick(self, round_number: int, card: int) -> ConceptRound:
        round_ = self._round(round_number)
        if not 1 <= card <= len(round_.cards):
            raise ValueError(f"round {round_number} has cards 1 to {len(round_.cards)}")
        for other in self.rounds:
            if other is not round_:
                other.picked = None
        round_.picked, round_.picked_utc = card, _utc()
        self.make_3d = None
        return round_

    def chosen(self) -> tuple[ConceptRound, ConceptCard] | None:
        for round_ in reversed(self.rounds):
            if round_.picked:
                return round_, round_.cards[round_.picked - 1]
        return None

    def request_3d(self) -> dict[str, Any]:
        chosen = self.chosen()
        if chosen is None:
            raise ValueError("pick a design first, then Make it 3D")
        round_, card = chosen
        self.make_3d = {"round": round_.number, "card": round_.picked, "title": card.title, "utc": _utc()}
        return dict(self.make_3d)

    def _round(self, number: int) -> ConceptRound:
        if not 1 <= number <= len(self.rounds):
            raise ValueError(f"there is no round {number}")
        return self.rounds[number - 1]

    def summary(self) -> dict[str, Any]:
        chosen = self.chosen()
        return {
            "rounds": len(self.rounds),
            "current_round": self.current.to_dict() if self.current else None,
            "picked": ({"round": chosen[0].number, "card": chosen[0].picked, "title": chosen[1].title} if chosen else None),
            "make_3d_requested": dict(self.make_3d) if self.make_3d else None,
            "history": [{"round": r.number, "note": r.note, "titles": [c.title for c in r.cards], "picked": r.picked} for r in self.rounds],
            "rule": "Do not build anything in 3D until make_3d_requested is set or the user tells you to make it 3D.",
        }

    def to_dict(self) -> dict[str, Any]:
        return {"rounds": [r.to_dict() for r in self.rounds], "make_3d": self.make_3d}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ConceptHistory":
        history = cls()
        for item in (data or {}).get("rounds") or []:
            cards = [ConceptCard(**{k: c[k] for k in ConceptCard.__dataclass_fields__ if k in c}) for c in item.get("cards") or []]
            round_ = ConceptRound(int(item["round"]), cards, str(item.get("note") or ""), str(item.get("utc") or _utc()),
                                  item.get("picked"), str(item.get("picked_utc") or ""))
            history.rounds.append(round_)
        history.make_3d = (data or {}).get("make_3d")
        return history
