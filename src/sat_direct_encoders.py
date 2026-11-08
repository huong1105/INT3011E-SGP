"""Mã hóa SGP thành CNF bằng mô hình ba chỉ số và bốn bộ Exactly-s."""

from itertools import combinations, product as iter_product
from pysat.card import CardEnc, EncType


PYSAT_ENCODING_MAP = {
    'seqcounter':  EncType.seqcounter,
    'totalizer':   EncType.totalizer,
    'cardnetwrk':  EncType.cardnetwrk,
}


ENCODING_MAP = {
    'nsc':         'nsc',
    'seqcounter':  'seqcounter',
    'totalizer':   'totalizer',
    'cardnetwrk':  'cardnetwrk',
}

ENCODING_DESCRIPTIONS = {
    'nsc':         'New Sequential Counter (Kieu, Nguyen & To)',
    'seqcounter':  'Sequential Counter (Sinz, 2005)',
    'totalizer':   'Totalizer (Bailleux & Boufkhad, 2003)',
    'cardnetwrk':  'Cardinality Network (Asin et al., 2009)',
}


def _positive_int(name: str, value: int) -> None:
    """Kiểm tra một tham số là số nguyên dương."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def _validate_cardinality(n: int, g: int, s: int, w: int,
                          top_id: int | None) -> int:
    """Kiểm tra kích thước, giới hạn cardinality và ID biến đã dùng."""
    for name, value in (("n", n), ("g", g), ("w", w)):
        _positive_int(name, value)
    if isinstance(s, bool) or not isinstance(s, int) or not 0 <= s <= n:
        raise ValueError("s must be an integer between 0 and n")
    primary_top = n * g * w
    if top_id is None:
        return primary_top
    if (isinstance(top_id, bool) or not isinstance(top_id, int)
            or top_id < primary_top):
        raise ValueError("top_id must be an integer at least n*g*w")
    return top_id


def _validate_encoding(encoding: str) -> None:
    """Kiểm tra tên bộ mã hóa được hỗ trợ."""
    if not isinstance(encoding, str) or encoding not in ENCODING_MAP:
        raise ValueError(
            f"Unknown encoding {encoding!r}; choose from {list(ENCODING_MAP)}"
        )


def _var_unchecked(i: int, j: int, k: int, g: int, w: int) -> int:
    """Ánh xạ chỉ số đã hợp lệ sang ID biến DIMACS."""
    return i * g * w + j * w + k + 1


def var(i: int, j: int, k: int, g: int, w: int) -> int:
    """Ánh xạ (người, nhóm, tuần) từ chỉ số 0-based sang ID DIMACS 1-based."""
    _positive_int("g", g)
    _positive_int("w", w)
    for name, value, limit in (("i", i, None), ("j", j, g), ("k", k, w)):
        if (isinstance(value, bool) or not isinstance(value, int) or value < 0
                or (limit is not None and value >= limit)):
            raise ValueError(f"{name} is outside its zero-based index domain")
    return _var_unchecked(i, j, k, g, w)


def decode_var(var_id: int, g: int, w: int) -> tuple[int, int, int]:
    """Giải mã ID DIMACS thành (người, nhóm, tuần) với chỉ số 0-based."""
    _positive_int("var_id", var_id)
    _positive_int("g", g)
    _positive_int("w", w)
    v = var_id - 1
    i = v // (g * w)
    remainder = v % (g * w)
    j = remainder // w
    k = remainder % w
    return (i, j, k)


def num_primary_vars(n: int, g: int, w: int) -> int:
    """Trả số biến chính n*g*w, không tính biến phụ."""
    for name, value in (("n", n), ("g", g), ("w", w)):
        _positive_int(name, value)
    return n * g * w


def encode_c1(n: int, g: int, w: int) -> list[list[int]]:
    """Sinh CNF bảo đảm mỗi người thuộc đúng một nhóm mỗi tuần."""
    for name, value in (("n", n), ("g", g), ("w", w)):
        _positive_int(name, value)
    clauses = []

    for i in range(n):
        for k in range(w):

            alo_clause = [_var_unchecked(i, j, k, g, w) for j in range(g)]
            clauses.append(alo_clause)


            for j1, j2 in combinations(range(g), 2):
                clauses.append([
                    -_var_unchecked(i, j1, k, g, w),
                    -_var_unchecked(i, j2, k, g, w),
                ])

    return clauses


def encode_c2_nsc(n: int, g: int, s: int, w: int,
                  top_id: int | None = None) -> tuple[list[list[int]], int]:
    """Sinh Exactly-s bằng NSC theo Eq. (2)-(9), trả CNF và ID cao nhất."""
    top_id = _validate_cardinality(n, g, s, w, top_id)
    p = s


    if s in (0, n):
        sign = 1 if s == n else -1
        return ([
            [sign * _var_unchecked(i, j, k, g, w)]
            for j in range(g) for k in range(w) for i in range(n)
        ], top_id)

    clauses = []

    for gj in range(g):
        for wk in range(w):


            r_var = {}
            for ri in range(n - 1):
                for rj in range(min(ri + 1, p)):
                    top_id += 1
                    r_var[(ri, rj)] = top_id


            def gvar(player: int, _gj=gj, _wk=wk, _g=g, _w=w) -> int:
                """Lấy ID biến của người trong nhóm và tuần hiện tại."""
                return _var_unchecked(player, _gj, _wk, _g, _w)


            for ri in range(n - 1):
                clauses.append([-gvar(ri), r_var[(ri, 0)]])


            for ri in range(p):
                clauses.append([gvar(ri), -r_var[(ri, ri)]])


            for ri in range(1, n - 1):
                for rj in range(min(ri, p)):
                    clauses.append([-r_var[(ri - 1, rj)], r_var[(ri, rj)]])


            for ri in range(1, n - 1):
                for rj in range(1, min(ri + 1, p)):
                    clauses.append([
                        -gvar(ri),
                        -r_var[(ri - 1, rj - 1)],
                        r_var[(ri, rj)]
                    ])


            for ri in range(1, n - 1):
                for rj in range(min(ri, p)):
                    clauses.append([
                        gvar(ri),
                        r_var[(ri - 1, rj)],
                        -r_var[(ri, rj)]
                    ])


            for ri in range(1, n - 1):
                for rj in range(1, min(ri + 1, p)):
                    clauses.append([r_var[(ri - 1, rj - 1)], -r_var[(ri, rj)]])


            r_final_p = r_var[(n - 2, p - 1)]
            g_last = gvar(n - 1)
            clauses.append([r_final_p, g_last])
            if p >= 2:
                r_final_p1 = r_var[(n - 2, p - 2)]
                clauses.append([r_final_p, r_final_p1])


            for player in range(p, n):
                clauses.append([-gvar(player), -r_var[(player - 1, p - 1)]])

    return clauses, top_id


def encode_c2_pysat(n: int, g: int, s: int, w: int,
                    encoding: str = 'seqcounter',
                    top_id: int | None = None) -> tuple[list[list[int]], int]:
    """Sinh Exactly-s bằng PySAT CardEnc.equals, trả CNF và ID cao nhất."""
    top_id = _validate_cardinality(n, g, s, w, top_id)
    if not isinstance(encoding, str) or encoding not in PYSAT_ENCODING_MAP:
        raise ValueError(f"Choose a PySAT encoding from {list(PYSAT_ENCODING_MAP)}")
    enc_type = PYSAT_ENCODING_MAP[encoding]
    clauses = []

    for j in range(g):
        for k in range(w):
            lits = [_var_unchecked(i, j, k, g, w) for i in range(n)]
            cnf = CardEnc.equals(lits=lits, bound=s,
                                 encoding=enc_type, top_id=top_id)
            clauses.extend(cnf.clauses)


            top_id = max(top_id, cnf.nv)

    return clauses, top_id


def encode_c2(n: int, g: int, s: int, w: int,
              encoding: str = 'nsc',
              top_id: int | None = None) -> tuple[list[list[int]], int]:
    """Chọn bộ mã hóa Exactly-s cho kích thước nhóm."""
    _validate_encoding(encoding)

    if encoding == 'nsc':
        return encode_c2_nsc(n, g, s, w, top_id)
    else:
        return encode_c2_pysat(n, g, s, w, encoding, top_id)


def encode_c3(n: int, g: int, w: int) -> list[list[int]]:
    """Sinh CNF cấm một cặp người cùng nhóm ở hai tuần khác nhau."""
    for name, value in (("n", n), ("g", g), ("w", w)):
        _positive_int(name, value)
    clauses = []

    for k1, k2 in combinations(range(w), 2):
        for j1, j2 in iter_product(range(g), repeat=2):
            for i1, i2 in combinations(range(n), 2):
                clauses.append([
                    -_var_unchecked(i1, j1, k1, g, w),
                    -_var_unchecked(i2, j1, k1, g, w),
                    -_var_unchecked(i1, j2, k2, g, w),
                    -_var_unchecked(i2, j2, k2, g, w),
                ])

    return clauses


def encode_sgp(w: int, g: int, s: int,
               encoding: str = 'nsc',
               symmetry_clauses: list[list[int]] | None = None
               ) -> tuple[list[list[int]], int, dict]:
    """Mã hóa SGP(w,g,s), trả (clauses, num_vars, stats); symmetry dùng biến chính."""
    for name, value in (("w", w), ("g", g), ("s", s)):
        _positive_int(name, value)
    _validate_encoding(encoding)
    n = g * s
    n_primary = num_primary_vars(n, g, w)
    sb_clauses = []
    if symmetry_clauses is not None:
        try:
            sb_clauses = [list(clause) for clause in symmetry_clauses]
        except TypeError as exc:
            raise ValueError("symmetry_clauses must contain iterable clauses") from exc
        for clause in sb_clauses:
            for lit in clause:
                if (isinstance(lit, bool) or not isinstance(lit, int)
                        or lit == 0 or abs(lit) > n_primary):
                    raise ValueError("symmetry_clauses must use nonzero primary literals")


    w_max = (n - 1) // (s - 1) if s > 1 else None
    precheck_unsat = w_max is not None and w > w_max
    unsat_reason = (
        f"w={w} exceeds floor((gs-1)/(s-1))={w_max}"
        if precheck_unsat else None
    )

    if precheck_unsat:


        clauses = [[]] + sb_clauses
        stats = {
            'n': n, 'g': g, 's': s, 'w': w, 'encoding': encoding,
            'encoding_desc': ENCODING_DESCRIPTIONS[encoding],
            'n_primary_vars': n_primary, 'n_aux_vars': 0,
            'n_total_vars': n_primary,
            'n_c1': 0, 'n_c2': 0, 'n_c3': 0, 'n_sb': len(sb_clauses),
            'n_precheck': 1, 'n_total_clauses': len(clauses),
            'w_max': w_max, 'precheck_unsat': True,
            'unsat_reason': unsat_reason,
        }
        return clauses, n_primary, stats


    c1_clauses = encode_c1(n, g, w)


    c2_clauses, top_id = encode_c2(n, g, s, w, encoding=encoding)


    c3_clauses = encode_c3(n, g, w)


    all_clauses = c1_clauses + c2_clauses + c3_clauses

    all_clauses.extend(sb_clauses)
    n_sb = len(sb_clauses)

    stats = {
        'n':              n,
        'g':              g,
        's':              s,
        'w':              w,
        'encoding':       encoding,
        'encoding_desc':  ENCODING_DESCRIPTIONS.get(encoding, encoding),
        'n_primary_vars': n_primary,
        'n_aux_vars':     top_id - n_primary,
        'n_total_vars':   top_id,
        'n_c1':           len(c1_clauses),
        'n_c2':           len(c2_clauses),
        'n_c3':           len(c3_clauses),
        'n_sb':           n_sb,
        'n_precheck':     0,
        'n_total_clauses': len(all_clauses),
        'w_max':          w_max,
        'precheck_unsat': False,
        'unsat_reason':   None,
    }

    return all_clauses, top_id, stats


def extract_schedule(model: list[int], n: int, g: int, s: int, w: int
                     ) -> dict[int, dict[int, list[int]]]:
    """Giải mã model đầy đủ thành schedule[tuần][nhóm] với chỉ số 0-based."""
    for name, value in (("n", n), ("g", g), ("s", s), ("w", w)):
        _positive_int(name, value)
    if n != g * s:
        raise ValueError("n must equal g*s when extracting an SGP schedule")
    max_primary = num_primary_vars(n, g, w)

    schedule = {k: {j: [] for j in range(g)} for k in range(w)}

    if isinstance(model, (str, bytes, dict)):
        raise ValueError("model must be an iterable of integer literals")
    try:
        literals = iter(model)
    except TypeError as exc:
        raise ValueError("model must be an iterable of integer literals") from exc
    seen = set()
    primary_assignments = 0
    for lit in literals:
        if isinstance(lit, bool) or not isinstance(lit, int) or lit == 0:
            raise ValueError("model must contain nonzero integer literals")
        if abs(lit) in seen:
            raise ValueError("model assigns the same variable more than once")
        seen.add(abs(lit))
        if abs(lit) <= max_primary:
            primary_assignments += 1
        if lit > 0 and lit <= max_primary:
            i, j, k = decode_var(lit, g, w)
            schedule[k][j].append(i)

    if primary_assignments != max_primary:
        raise ValueError("model does not assign every primary variable")


    for k in range(w):
        for j in range(g):
            schedule[k][j].sort()

    return schedule


def format_schedule(schedule: dict[int, dict[int, list[int]]],
                    one_based: bool = True) -> str:
    """Định dạng lịch; one_based=True hiển thị người bắt đầu từ 1."""
    offset = 1 if one_based else 0
    lines = []

    for k in sorted(schedule.keys()):
        groups_str = []
        for j in sorted(schedule[k].keys()):
            players = [str(p + offset) for p in schedule[k][j]]
            groups_str.append("{" + ", ".join(players) + "}")
        lines.append(f"  Week {k + 1}: " + "  ".join(groups_str))

    return "\n".join(lines)


if __name__ == "__main__":
    import time
    from pysat.solvers import Solver

    def run_test(w, g, s, encoding='nsc', solver_name='Cadical153'):
        """Sinh CNF, giải và trả lịch của một ví dụ SGP."""
        n = g * s
        clauses, nv, stats = encode_sgp(w, g, s, encoding=encoding)

        with Solver(name=solver_name, bootstrap_with=clauses) as solver:
            t0 = time.perf_counter()
            is_sat = solver.solve()
            t = time.perf_counter() - t0
            model = solver.get_model() if is_sat else None

        status = 'SAT' if is_sat else 'UNSAT'
        print(f"  [{stats['encoding_desc'][:40]:40s}]  "
              f"vars={stats['n_total_vars']:6d} (aux={stats['n_aux_vars']:5d})  "
              f"clauses={stats['n_total_clauses']:6d}  "
              f"status={status}  time={t:.4f}s")

        if is_sat and model:
            sched = extract_schedule(model, n, g, s, w)
            return sched
        return None


    print("=" * 100)
    print("SGP(w=2, g=2, s=2) -- n=4 players")
    print("=" * 100)
    sched = None
    for enc in ENCODING_MAP:
        result = run_test(2, 2, 2, encoding=enc)
        if result and sched is None:
            sched = result
    if sched:
        print("\n  Schedule (NSC):")
        print(format_schedule(sched))


    print("\n" + "=" * 100)
    print("SGP(w=3, g=3, s=3) -- n=9 players")
    print("=" * 100)
    for enc in ENCODING_MAP:
        run_test(3, 3, 3, encoding=enc)


    print("\n" + "=" * 100)
    print("SGP(w=4, g=4, s=4) -- n=16 players")
    print("=" * 100)
    for enc in ENCODING_MAP:
        run_test(4, 4, 4, encoding=enc)


    print("\n" + "=" * 100)
    print("SGP(w=3, g=2, s=2) -- n=4 players (full schedule)")
    print("=" * 100)
    sched = run_test(3, 2, 2)
    if sched:
        print("\n  Schedule:")
        print(format_schedule(sched))


    print("\n" + "=" * 100)
    print("SGP(w=4, g=3, s=3) -- n=9 players (full schedule)")
    print("=" * 100)
    sched = run_test(4, 3, 3)
    if sched:
        print("\n  Schedule:")
        print(format_schedule(sched))
