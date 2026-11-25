# Social Golfer Problem (SGP)

BTL2 môn Các vấn đề hiện đại trong KHMT, VNU-UET. Dự án so sánh SAT
one-hot ba chỉ số, SAT Order Encoding, OR-Tools CP-SAT và Gurobi ILP.

## Mô hình và encoding

API nhận `SGP(w, g, s)` với `w` tuần, `g` nhóm mỗi tuần và `s` người mỗi
nhóm. Tổng số người là `n = g * s`. Nhãn `g-p-w` trong bài nguồn dùng
`p = s`, nên `2-2-3` tương ứng `SGP(3, 2, 2)`.

Mô hình one-hot ba chỉ số dựa trên phần ràng buộc cơ bản của NSE. C1 dùng
ALO và pairwise AMO để xếp mỗi người vào đúng một nhóm mỗi tuần. C2 dùng
Exactly-`s` để cố định kích thước nhóm. C3 dùng các mệnh đề bốn literal âm
để cấm một cặp gặp nhau nhiều lần. Bốn cấu hình chỉ thay cách mã hóa C2.

| `encoding` | Bộ mã hóa C2 |
| --- | --- |
| `nsc` | New Sequential Counter |
| `seqcounter` | Sequential Counter |
| `totalizer` | Totalizer |
| `cardnetwrk` | Cardinality Network |

Có thể truyền ràng buộc phá đối xứng qua `symmetry_clauses` bằng ID của
các biến chính (`1..n*g*w`).

## Cài đặt

Chạy các lệnh từ thư mục gốc repository với Python 3.10 trở lên.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-sat.txt
```

Trên Linux/macOS, kích hoạt bằng `source .venv/bin/activate`. Để chạy
benchmark chung và vẽ biểu đồ, cài `python -m pip install -r requirements.txt`.

## Chạy SAT

```powershell
python -m src.sat_runner -w 3 -g 2 -s 2 --encoding nsc --solver cadical --timeout 10
python -m src.sat_runner -w 3 -g 2 -s 2 --encoding totalizer --solver cadical --timeout 10 --json
```

CLI độc lập dùng PySAT với `cadical` (CaDiCaL 1.5.3) hoặc `glucose`
(Glucose 4.1). Mặc định là `nsc`, `cadical` và timeout backend 60 giây.
Có thể xuất DIMACS qua CLI chung của nhóm.

```powershell
python main.py -w 3 -g 2 -s 2 --method sat --amo nsc --solver cadical --export-cnf output/example.cnf
```

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

Kết quả phân biệt `SAT`, `UNSAT`, `TIMEOUT`, `UNAVAILABLE` và `ERROR`.
Một kết quả SAT hợp lệ có `model_verified=True`, `verified=True` và `schedule`.
Với `s > 1`, nếu `w * (s - 1) > n - 1` thì API trả `UNSAT` với
`backend_type="precheck"` trước khi gọi solver. CSV benchmark dùng trạng thái
`UNSAT_PRECHECK` cho trường hợp này.

`timeout_seconds` trong API giới hạn thời gian backend khởi động, nạp CNF
và giải. API mặc định không đặt timeout. `encode_time_seconds` đo thời gian
sinh CNF, `wall_time_seconds` đo wall time của backend,
`solver_wall_time_seconds` đo riêng bước giải và `total_time_seconds` đo quá
trình sinh, giải và kiểm chứng. `cpu_time_seconds` có giá trị khi worker đo được.

Nếu chỉ cần CNF, dùng `encode_sgp(w, g, s, encoding=...)` trong
`src.sat_direct_encoders`; hàm trả `(clauses, num_vars, stats)`.
Nếu đã có CNF, gọi `solve_cnf(clauses, solver=..., timeout_seconds=...)`
trong `src.sat_runner`.

Chạy `python -m unittest discover -s tests -v` để kiểm thử bộ mã hóa và runner.

## Benchmark so sánh

Lượt benchmark đã lưu dùng 64 bài được bật trong danh sách đầu vào, `--sb none`,
một luồng và ngân sách 60 giây mỗi cấu hình. Đồng hồ của worker bắt đầu sau
khi nạp module của phương pháp và khởi tạo môi trường Gurobi cho ILP, rồi
tính từ dựng mô hình đến kiểm chứng. Giới hạn tài nguyên cho SAT/Order dựa
trên ước lượng số mệnh đề C3.
[Danh sách đầu vào](benchmarks/benchmark_instances.csv) · [CSV kết quả](benchmarks/results.csv) · [Metadata](benchmarks/results.csv.meta.json)

Trong 768 dòng kết quả, 512 dòng là SAT one-hot (`64 bài × 4 encoding × 2 solver`).
Nhánh này có 240 cấu hình tìm được lịch hợp lệ trên 33 bài, 56 `UNSAT_PRECHECK`,
200 `TIMEOUT` và 16 `SKIPPED_RESOURCE_LIMIT`. Hai trạng thái cuối biểu thị các
cấu hình chưa đưa ra quyết định SAT/UNSAT.

Để chạy lại đủ bốn phương pháp, cài dependency chung, cấu hình giấy phép
Gurobi và ghi vào một file mới. Giữ `.meta.json` cạnh CSV để tiếp tục bằng
`--resume` với cùng cấu hình.

```powershell
python -m benchmarks.run_all --instances benchmarks/benchmark_instances.csv --output output/benchmark_reproduction/results.csv --sb none --run-budget 60 --threads 1 --resume
```

Để dựng lại biểu đồ CNSPlots từ dữ liệu đã lưu, chạy lệnh dưới đây. Các biểu
đồ dùng `total_time_seconds` và ngân sách ghi trong metadata.

```powershell
python -m benchmarks.plot_cns --input benchmarks/results.csv --output-dir output/benchmark_reproduction/figures
```

Mô hình SAT, công thức đếm CNF và phần thực nghiệm nằm trong [báo cáo LaTeX](paper/main.tex).
