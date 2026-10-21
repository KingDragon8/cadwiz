# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Vendor-neutral purchased-hardware contracts and stack calculations."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil


@dataclass(frozen=True, slots=True)
class PurchaseOption:
    vendor: str
    title: str
    url: str
    checked_date: str
    vendor_part_number: str | None = None
    availability: str = "unknown"
    approximate_price: str | None = None


@dataclass(frozen=True, slots=True)
class HardwareDefinition:
    role: str
    generic_name: str
    thread_standard: str
    diameter_mm: float
    pitch_mm: float
    length_mm: float | None
    material: str
    style: str
    quantity: int
    dimensional_assumptions: tuple[str, ...]
    selection_reason: str
    alternate_lengths_mm: tuple[float, ...] = ()
    purchase_options: tuple[PurchaseOption, ...] = ()


def calculate_pivot_stack(
    lug_1_mm: float,
    lug_2_mm: float,
    indexed_faces_mm: float,
    washer_stack_mm: float,
    wing_nut_engagement_mm: float,
    tolerance_mm: float,
) -> float:
    values = (
        lug_1_mm,
        lug_2_mm,
        indexed_faces_mm,
        washer_stack_mm,
        wing_nut_engagement_mm,
        tolerance_mm,
    )
    if any(value <= 0 for value in values):
        raise ValueError("pivot stack dimensions must be positive")
    return sum(values)


def choose_standard_length(required_mm: float, available_mm: tuple[float, ...]) -> float:
    if required_mm <= 0 or not available_mm:
        raise ValueError("required length and available lengths are required")
    candidates = sorted(length for length in available_mm if length >= required_mm)
    if not candidates:
        raise ValueError("no available bolt length satisfies the calculated stack")
    return candidates[0]


def thread_turns(engagement_mm: float, pitch_mm: float) -> int:
    if engagement_mm <= 0 or pitch_mm <= 0:
        raise ValueError("engagement and pitch must be positive")
    return ceil(engagement_mm / pitch_mm)
