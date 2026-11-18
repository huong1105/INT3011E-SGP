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
        return False, ["Schedule phải là dict dạng schedule[week][group] -> list[player]"]

    expected_weeks = set(range(w))
    if any(isinstance(k, bool) or not isinstance(k, int) for k in schedule):
        return False, ["Chỉ số tuần phải là số nguyên 0-based"]
    if set(schedule.keys()) != expected_weeks:
        return False, [
            f"Tập tuần không hợp lệ: nhận {sorted(schedule.keys())}, yêu cầu 0..{w - 1}"
        ]

    n = g * s
    expected_groups = set(range(g))
    expected_players = set(range(n))
    met_pairs: dict[tuple[int, int], tuple[int, int]] = {}

    for week in range(w):
        groups = schedule[week]
        if not isinstance(groups, dict):
            errors.append(f"Tuần {week}: cấu trúc nhóm phải là dict")
            continue
        if any(isinstance(j, bool) or not isinstance(j, int) for j in groups):
            errors.append(f"Tuần {week}: chỉ số nhóm phải là số nguyên 0-based")
            continue
        if set(groups.keys()) != expected_groups:
            errors.append(
                f"Tuần {week}: tập nhóm không hợp lệ (nhận {sorted(groups.keys())}, yêu cầu 0..{g - 1})"
            )
            continue

        week_players: list[int] = []
        for group in range(g):
            members = groups[group]
            if not isinstance(members, (list, tuple)):
                errors.append(
                    f"Tuần {week}, Nhóm {group}: danh sách người chơi phải là list hoặc tuple"
                )
                continue

            if len(members) != s:
                errors.append(
                    f"Luật 2 - Tuần {week}, Nhóm {group}: có {len(members)} người (yêu cầu {s})"
                )

            invalid_members = [
                p
                for p in members
                if isinstance(p, bool) or not isinstance(p, int) or not (0 <= p < n)
            ]
            if invalid_members:
                errors.append(
                    f"Luật 2 - Tuần {week}, Nhóm {group}: chứa người chơi ngoài miền 0..{n - 1}: {invalid_members}"
                )
                continue

            if len(set(members)) != len(members):
                dup_in_group = [p for p, cnt in Counter(members).items() if cnt > 1]
                errors.append(
                    f"Luật 1/2 - Tuần {week}, Nhóm {group}: người chơi bị trùng trong cùng nhóm: {dup_in_group}"
                )

            week_players.extend(members)

            for p1, p2 in combinations(sorted(set(members)), 2):
                pair = (p1, p2)
                if pair in met_pairs:
                    prev_week, prev_group = met_pairs[pair]
                    errors.append(
                        f"Luật 3 - Cặp ({p1}, {p2}) gặp lại ở Tuần {week} Nhóm {group} "
                        f"(đã gặp ở Tuần {prev_week} Nhóm {prev_group})"
                    )
                else:
                    met_pairs[pair] = (week, group)

        counts = Counter(week_players)
        missing = sorted(expected_players - set(counts.keys()))
        duplicates = sorted(p for p, cnt in counts.items() if cnt > 1)
        if missing:
            errors.append(f"Luật 1 - Tuần {week}: thiếu người chơi {missing}")
        if duplicates:
            errors.append(
                f"Luật 1 - Tuần {week}: người chơi xuất hiện nhiều hơn 1 lần {duplicates}"
            )

    return len(errors) == 0, errors


def is_valid_schedule(schedule: Any, w: int, g: int, s: int) -> bool:
    """Trả về True nếu lịch hợp lệ."""
    valid, _ = verify_schedule(schedule, w, g, s)
    return valid
