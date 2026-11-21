from __future__ import annotations

from .io_utils import VALID_SB_MODES
from .sat_direct_encoders import var

def generate_symmetry_clauses(w: int, g: int, s: int, mode: str = "none") -> list[list[int]]:
    """Trả danh sách clause SB trên biến chính theo chế độ none/sb1/full."""
    for name, value in (("w", w), ("g", g), ("s", s)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name} must be a positive integer, got {value!r}")
    if not isinstance(mode, str) or mode not in VALID_SB_MODES:
        raise ValueError(f"mode must be one of {VALID_SB_MODES}, got {mode!r}")

    clauses: list[list[int]] = []
    if mode == "none":
        return clauses

    # SB1: tuần 0 chuẩn tắc, người i thuộc nhóm i//s.
    for j in range(g):
        for c in range(s):
            clauses.append([var(j * s + c, j, 0, g, w)])

    # SB2: từ tuần 1, người i thuộc nhóm i với i < min(g, s).
    if mode == "full" and w > 1:
        limit = min(g, s)
        for k in range(1, w):
            for i in range(limit):
                clauses.append([var(i, i, k, g, w)])

    return clauses

if __name__ == "__main__":
    # Tự kiểm tra: SB không được cắt mất nghiệm trên các instance đã biết.
    from pysat.solvers import Solver

    from .sat_direct_encoders import encode_sgp

    cases = [(2, 2, 2), (3, 2, 2), (3, 3, 3), (4, 3, 3), (2, 3, 2), (3, 3, 1)]
    print(f"{'w-g-s':>8} {'none':>6} {'sb1':>6} {'full':>6} {'n_sb':>5}")
    for w, g, s in cases:
        verdicts = []
        for mode in ("none", "sb1", "full"):
            clauses, _, stats = encode_sgp(
                w, g, s, "nsc",
                None if mode == "none" else generate_symmetry_clauses(w, g, s, mode=mode),
            )
            if stats.get("precheck_unsat"):
                verdicts.append("UNSAT")
                continue
            with Solver(name="cadical153", bootstrap_with=clauses) as sv:
                verdicts.append("SAT" if sv.solve() else "UNSAT")
        n_sb = len(generate_symmetry_clauses(w, g, s, mode="full"))
        flag = "" if len(set(verdicts)) == 1 else "  <<< KHAC NHAU"
        print(f"{f'{w}-{g}-{s}':>8} {verdicts[0]:>6} {verdicts[1]:>6} {verdicts[2]:>6} {n_sb:>5}{flag}")