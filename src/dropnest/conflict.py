"""Deterministic, case-insensitive conflict naming."""

from __future__ import annotations

from pathlib import Path

from dropnest.models import ItemType


def split_name_for_counter(name: str, item_type: ItemType) -> tuple[str, str]:
    """Split a name into the counter stem and preserved suffix sequence."""
    if item_type is ItemType.DIRECTORY:
        return name, ""
    suffixes = Path(name).suffixes
    suffix = "".join(suffixes)
    if not suffix:
        return name, ""
    return name[: -len(suffix)], suffix


def available_name(
    original_name: str,
    item_type: ItemType,
    occupied_casefolded: set[str],
) -> tuple[str, bool]:
    """Return and reserve the first name not occupied case-insensitively."""
    if original_name.casefold() not in occupied_casefolded:
        occupied_casefolded.add(original_name.casefold())
        return original_name, False

    stem, suffix = split_name_for_counter(original_name, item_type)
    counter = 1
    while True:
        candidate = f"{stem} ({counter}){suffix}"
        folded = candidate.casefold()
        if folded not in occupied_casefolded:
            occupied_casefolded.add(folded)
            return candidate, True
        counter += 1
