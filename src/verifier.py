"""Kiểm chứng lời giải SGP."""

from __future__ import annotations

from collections import Counter
from itertools import combinations
from typing import Any


def _validate_positive_int(name: str, value: Any) -> None:
    """Kiểm tra tham số nguyên dương."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer, got {value!r}")


def normalize_schedule(
    raw_schedule: Any,
    w: int,
    g: int,
    s: int,
    one_based: bool = False,
) -> dict[int, dict[int, list[int]]]:
    """Chuẩn hóa lịch về dạng dict 0-based."""
    _validate_positive_int("w", w)
    _validate_positive_int("g", g)
    _validate_positive_int("s", s)
    offset = 1 if one_based else 0

    if isinstance(raw_schedule, list):
        week_items = enumerate(raw_schedule)
    elif isinstance(raw_schedule, dict):
        week_items = raw_schedule.items()
    else:
        raise ValueError("raw_schedule must be a dict or list of weeks")

    normalized: dict[int, dict[int, list[int]]] = {}
    for raw_week, raw_groups in week_items:
        if isinstance(raw_week, bool) or not isinstance(raw_week, int):
            raise ValueError(f"Week index must be int, got {raw_week!r}")
        week_idx = raw_week - offset if isinstance(raw_schedule, dict) else raw_week

        if isinstance(raw_groups, list):
            group_items = enumerate(raw_groups)
        elif isinstance(raw_groups, dict):
            group_items = raw_groups.items()
        else:
            raise ValueError(f"Week {week_idx}: groups must be a dict or list")

        normalized[week_idx] = {}
        for raw_group, raw_players in group_items:
            if isinstance(raw_group, bool) or not isinstance(raw_group, int):
                raise ValueError(f"Group index must be int, got {raw_group!r}")
            group_idx = (
                raw_group - offset if isinstance(raw_groups, dict) else raw_group
            )
            if isinstance(raw_players, (str, bytes, dict)):
                raise ValueError(
                    f"Week {week_idx}, Group {group_idx}: players must be a list/tuple/set"
                )
            try:
                players_list = list(raw_players)
            except TypeError as exc:
                raise ValueError(
                    f"Week {week_idx}, Group {group_idx}: players must be iterable"
                ) from exc

            converted: list[int] = []
            for player in players_list:
                if isinstance(player, bool) or not isinstance(player, int):
                    raise ValueError(
                        f"Week {week_idx}, Group {group_idx}: player must be int, got {player!r}"
                    )
                converted.append(player - offset)
            normalized[week_idx][group_idx] = sorted(converted)

    return normalized


def verify_schedule(
    schedule: Any,
    w: int,
    g: int,
    s: int,
) -> tuple[bool, list[str]]:
    """Kiểm chứng lời giải SGP, trả về (is_valid, errors)."""
    try:
        _validate_positive_int("w", w)
        _validate_positive_int("g", g)
        _validate_positive_int("s", s)
    except ValueError as exc:
        return False, [str(exc)]

    errors: list[str] = []
    if not isinstance(schedule, dict):
        return False, ["Schedule must be a dict: schedule[week][group] -> list[player]"]

    expected_weeks = set(range(w))
    if any(isinstance(k, bool) or not isinstance(k, int) for k in schedule):
        return False, ["Week indices must be 0-based integers"]
    if set(schedule.keys()) != expected_weeks:
        return False, [
            f"Invalid week keys: got {sorted(schedule.keys())}, expected 0..{w - 1}"
        ]

    n = g * s
    expected_groups = set(range(g))
    expected_players = set(range(n))
    met_pairs: dict[tuple[int, int], tuple[int, int]] = {}

    for week in range(w):
        groups = schedule[week]
        if not isinstance(groups, dict):
            errors.append(f"Week {week}: groups must be a dict")
            continue
        if any(isinstance(j, bool) or not isinstance(j, int) for j in groups):
            errors.append(f"Week {week}: group indices must be 0-based integers")
            continue
        if set(groups.keys()) != expected_groups:
            errors.append(
                f"Week {week}: invalid group keys (got {sorted(groups.keys())}, expected 0..{g - 1})"
            )
            continue

        week_players: list[int] = []
        for group in range(g):
            members = groups[group]
            if not isinstance(members, (list, tuple)):
                errors.append(
                    f"Week {week}, Group {group}: members must be a list or tuple"
                )
                continue

            if len(members) != s:
                errors.append(
                    f"Rule 2 - Week {week}, Group {group}: size {len(members)} (expected {s})"
                )

            invalid_members = [
                p
                for p in members
                if isinstance(p, bool) or not isinstance(p, int) or not (0 <= p < n)
            ]
            if invalid_members:
                errors.append(
                    f"Rule 2 - Week {week}, Group {group}: players out of range 0..{n - 1}: {invalid_members}"
                )
                continue

            if len(set(members)) != len(members):
                dup_in_group = [p for p, cnt in Counter(members).items() if cnt > 1]
                errors.append(
                    f"Rule 1/2 - Week {week}, Group {group}: duplicate players in group: {dup_in_group}"
                )

            week_players.extend(members)

            for p1, p2 in combinations(sorted(set(members)), 2):
                pair = (p1, p2)
                if pair in met_pairs:
                    prev_week, prev_group = met_pairs[pair]
                    errors.append(
                        f"Rule 3 - Pair ({p1}, {p2}) repeated at Week {week} Group {group} "
                        f"(previously met at Week {prev_week} Group {prev_group})"
                    )
                else:
                    met_pairs[pair] = (week, group)

        counts = Counter(week_players)
        missing = sorted(expected_players - set(counts.keys()))
        duplicates = sorted(p for p, cnt in counts.items() if cnt > 1)
        if missing:
            errors.append(f"Rule 1 - Week {week}: missing players {missing}")
        if duplicates:
            errors.append(
                f"Rule 1 - Week {week}: players appear more than once {duplicates}"
            )

    return len(errors) == 0, errors


def is_valid_schedule(schedule: Any, w: int, g: int, s: int) -> bool:
    """Trả về True nếu lịch hợp lệ."""
    valid, _ = verify_schedule(schedule, w, g, s)
    return valid
