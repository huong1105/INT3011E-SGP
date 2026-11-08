# Social Golfer Problem — SAT Solver

Phần SAT của BTL2 môn Các vấn đề hiện đại trong KHMT, VNU-UET.
Code cung cấp bộ sinh CNF và runner độc lập để tích hợp với các phần của nhóm.

## Mô hình và encoding

API nhận `SGP(w, g, s)`: `w` tuần, `g` nhóm mỗi tuần, `s` người mỗi nhóm;
tổng số người là `g * s`. Nhãn `(g,p,w)` trong bài nguồn tương ứng `s=p`.

Mô hình dùng biến one-hot ba chỉ số theo NSE:

- C1: mỗi người thuộc đúng một nhóm mỗi tuần, bằng ALO và pairwise AMO.
- C2: mỗi nhóm có đúng `s` người, chọn một trong bốn encoding bên dưới.
- C3: mỗi cặp người gặp nhau nhiều nhất một lần, bằng clause bốn literal âm.

| `encoding` | Bộ mã hóa C2 |
| --- | --- |
| `nsc` | New Sequential Counter |
| `seqcounter` | Sequential Counter |
| `totalizer` | Totalizer |
| `cardnetwrk` | Cardinality Network |

Symmetry breaking được truyền riêng qua `symmetry_clauses`; bộ sinh không tự
thêm ràng buộc symmetry của các module khác.

## Cài đặt

Chạy các lệnh từ thư mục gốc repository với Python 3.10 trở lên.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-sat.txt
```

Trên Linux/macOS, kích hoạt bằng `source .venv/bin/activate`. File
`requirements.txt` cài thêm dependency cho các phần khác của dự án.

## Chạy SAT

```powershell
python -m src.sat_runner -w 3 -g 2 -s 2 --encoding nsc --solver cadical --timeout 10
python -m src.sat_runner -w 3 -g 2 -s 2 --encoding totalizer --solver cadical --timeout 10 --json
```

Hai solver: `cadical` (CaDiCaL 1.5.3) và `glucose` (Glucose 4.1). CLI SAT chạy trực tiếp bằng `src.sat_runner`.
Mặc định CLI dùng `nsc`, `cadical` và timeout backend 60 giây.

## Dùng trong code của nhóm

```python
from src.sat_runner import solve_sgp

result = solve_sgp(3, 2, 2, encoding="nsc", solver="cadical", timeout_seconds=10)
print(result["status"])
if result["status"] == "SAT":
    assert result["verified"]
    schedule = result["schedule"]
    # schedule[week][group] là danh sách player; tất cả chỉ số bắt đầu từ 0.
```

Kết quả phân biệt `SAT`, `UNSAT`, `TIMEOUT`, `UNAVAILABLE`, `ERROR`.
Runner kiểm tra model CNF và lịch SGP trước khi trả SAT có `verified=True`.
`timeout_seconds` giới hạn khởi động backend, nạp CNF và solve; thời gian
sinh CNF được ghi riêng trong `encode_time_seconds`. API mặc định không đặt timeout.

Nếu chỉ cần CNF, dùng `encode_sgp(w, g, s, encoding=...)` trong
`src.sat_direct_encoders`; hàm trả `(clauses, num_vars, stats)`.
Nếu đã có CNF, gọi `solve_cnf(clauses, solver=..., timeout_seconds=...)`
trong `src.sat_runner`.
