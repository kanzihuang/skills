"""COCA frequency band computation for Anki sub-decks.

Groups COCA word-family levels (1–25) into balanced sub-deck bands
based on actual word counts, so users can study by frequency tier.
"""

from __future__ import annotations


def compute_bands(
    level_counts: dict[int, int],
    max_bands: int = 5,
    min_band_size: int = 100,
) -> list[tuple[str, int, int]] | None:
    """Group COCA levels into balanced bands based on actual word counts.

    Greedy partition: walk levels in ascending order, cut when accumulated
    count reaches target (= total / K).  Post-process: merge undersized
    tail band into previous band.

    Returns list of (band_name, lo, hi) or None if no banding needed.
    """
    if not level_counts:
        return None

    total = sum(level_counts.values())
    if total < min_band_size:
        return None

    sorted_levels = sorted(level_counts.keys())
    if len(sorted_levels) <= 1:
        return None

    k = min(max_bands, len(sorted_levels), total // min_band_size)
    if k <= 1:
        return None

    target = total / k

    bands: list[tuple[int, int, int]] = []  # (lo, hi, count)
    current_lo = sorted_levels[0]
    current_sum = 0
    prev_level = current_lo

    for level in sorted_levels:
        count = level_counts[level]
        gap_cut = (level - prev_level > 1 and current_sum >= min_band_size)
        target_cut = (current_sum > 0 and current_sum >= target
                      and len(bands) < k - 1)
        if gap_cut or target_cut:
            bands.append((current_lo, prev_level, current_sum))
            current_lo = level
            current_sum = 0
        current_sum += count
        prev_level = level

    bands.append((current_lo, sorted_levels[-1], current_sum))

    if len(bands) <= 1:
        return None

    # Post-process: merge undersized bands
    changed = True
    while changed and len(bands) >= 2:
        changed = False
        for i in range(len(bands)):
            _lo, _hi, cnt = bands[i]
            if cnt < min_band_size and len(bands) >= 2:
                if i == 0:
                    bands[1] = (bands[i][0], bands[1][1], cnt + bands[1][2])
                    bands.pop(i)
                elif i == len(bands) - 1:
                    bands[i - 1] = (bands[i - 1][0], bands[i][1],
                                    bands[i - 1][2] + cnt)
                    bands.pop(i)
                else:
                    if bands[i - 1][2] <= bands[i + 1][2]:
                        bands[i - 1] = (bands[i - 1][0], bands[i][1],
                                        bands[i - 1][2] + cnt)
                    else:
                        bands[i + 1] = (bands[i][0], bands[i + 1][1],
                                        cnt + bands[i + 1][2])
                    bands.pop(i)
                changed = True
                break

    if len(bands) <= 1:
        return None

    result: list[tuple[str, int, int]] = []
    for lo, hi, _count in bands:
        if lo == hi:
            result.append((f"COCA {lo}", lo, hi))
        else:
            result.append((f"COCA {lo}-{hi}", lo, hi))

    return result


def _count_coca_levels(words: list[dict]) -> dict[int, int]:
    """Count words per COCA level from the words array."""
    level_counts: dict[int, int] = {}
    for w in words:
        lvl = w.get("coca_level")
        if isinstance(lvl, int) and 1 <= lvl <= 25:
            level_counts[lvl] = level_counts.get(lvl, 0) + 1
    return level_counts


def _pre_assign_bands(
    words: list[dict],
    deck_name: str,
    bands: list[tuple[str, int, int]],
    band_assignment: dict[int, str],
) -> None:
    """Pre-assign each word in the full list to its target deck.

    Populates band_assignment with {word_index: target_deck_name}.
    Words without a valid coca_level default to the parent deck.
    """
    band_map: dict[tuple[int, int], str] = {}
    for band_name, lo, hi in bands:
        band_map[(lo, hi)] = f"{deck_name}::{band_name}"
    for idx, w in enumerate(words):
        lvl = w.get("coca_level")
        assigned = False
        if isinstance(lvl, int):
            for (lo, hi), sub_deck in band_map.items():
                if lo <= lvl <= hi:
                    band_assignment[idx] = sub_deck
                    assigned = True
                    break
        if not assigned:
            band_assignment[idx] = deck_name
