# Social Golfer Problem (SGP) - Exact Solving Suite

Dự án Bài tập lớn số 2 (BTL2) môn **Các vấn đề hiện đại trong KHMT** - Trường Đại học Công nghệ, ĐHQGHN (VNU-UET).

Nghiên cứu và so sánh đối đầu các phương pháp giải chính xác (Exact Approaches) cho bài toán **Social Golfer Problem - SGP(w, g, s)**:
- **SAT Solving:** Direct Encoding kết hợp 4 kỹ thuật AMO/Cardinality (*Sequential Counter, Commander, Binary, Product*) và *Order Encoding*.
- **Constraint Programming (CP):** Google OR-Tools CP-SAT.
- **Integer Linear Programming (ILP):** Gurobi Optimizer / OR-Tools MIP.
- **Symmetry Breaking (SB):** SB1 (Fix Tuần 1), SB2 (Thứ tự nhóm), SB3 (Nội bộ nhóm), SB4 (Thứ tự tuần).
- **Trực quan hóa:** Thư viện `cnsplots` / `matplotlib`.

---

## 👥 Thành viên nhóm & Phân công
- **Thành viên 1:** Lead I/O, Solution Verifier, CP Solver (OR-Tools), CNSPlots & Báo cáo Elsevier.
- **Thành viên 2:** 4 Bộ AMO/Cardinality Encoders (SeqCounter, Commander, Binary, Product), Đa SAT Solvers (CaDiCaL, Glucose, Kissat) & Quản lý GitHub.
- **Thành viên 3:** Order Encoding, ILP Solver (Gurobi/MIP), 4 Kỹ thuật Symmetry Breaking (SB1–SB4) & Benchmark Suite.

---

## 📁 Cấu trúc thư mục
```text
sgp-solver/
│
├── src/
│   ├── __init__.py
│   ├── io_utils.py           # [TV1] CLI parser, kiểm tra cận w_max, xuất DIMACS .cnf
│   ├── verifier.py           # [TV1] Universal Solution Verifier kiểm tra tính đúng đắn
│   ├── display.py            # [TV1] Định dạng bảng lịch thi đấu ma trận
│   ├── cp_solver.py          # [TV1] Mô hình Google OR-Tools CP-SAT
│   ├── sat_direct_encoders.py# [TV2] Direct Encoding + 4 bộ AMO (SeqCounter, Commander, Binary, Product)
│   ├── sat_runner.py         # [TV2] Bộ chạy đa SAT Solvers (Cadical, Glucose, Kissat)
│   ├── order_encoder.py      # [TV3] Mô hình Order Encoding
│   ├── ilp_solver.py         # [TV3] Mô hình ILP (Gurobi/MIP)
│   └── symmetry.py           # [TV3] 4 kỹ thuật SB1, SB2, SB3, SB4
│
├── benchmarks/               # [TV3 + TV1] Đo đạc và vẽ đồ thị khoa học
│   ├── run_all.py            # Script chạy tự động toàn bộ test cases
│   ├── plot_cns.py           # Script vẽ biểu đồ bằng cnsplots
│   └── data/                 # Chứa dữ liệu kết quả đo đạc CSV
│
├── paper/                    # [Cả nhóm] Bản thảo bài báo khoa học Elsevier cas-sc
│   ├── main.tex
│   └── figures/
│
├── main.py                   # Điểm khởi chạy chương trình thống nhất (CLI)
├── requirements.txt          # Các thư viện phụ thuộc
└── README.md                 # Tài liệu hướng dẫn
```

---

## 🚀 Cài đặt môi trường
Yêu cầu Python 3.9 trở lên.
```bash
# 1. Tạo môi trường ảo
python -m venv venv

# Kích hoạt trên Windows:
.\venv\Scripts\activate
# Kích hoạt trên Linux/macOS:
source venv/bin/activate

# 2. Cài đặt các thư viện phụ thuộc
pip install -r requirements.txt
```

---

## 💻 Hướng dẫn chạy chương trình

### 1. Giải bằng SAT Solving (Mặc định: Direct + Sequential Counter + CaDiCaL)
```bash
python main.py -w 4 -g 3 -s 3 --method sat --amo seqcounter --solver cadical --sb full
```

Các tùy chọn bộ mã hóa AMO/Cardinality (`--amo`):
- `seqcounter`: Sequential Counter Encoding
- `commander`: Commander Encoding
- `binary`: Binary / Bitwise Encoding
- `product`: Product Encoding

Các tùy chọn SAT Solver (`--solver`):
- `cadical`, `glucose`, `kissat`

Tùy chọn Symmetry Breaking (`--sb`):
- `none`: Không dùng SB
- `sb1`: Chỉ cố định tuần 1
- `full`: Toàn bộ SB1 + SB2 + SB3 + SB4

### 2. Giải bằng Order Encoding
```bash
python main.py -w 4 -g 3 -s 3 --method order
```

### 3. Giải bằng Constraint Programming (CP-SAT)
```bash
python main.py -w 4 -g 3 -s 3 --method cp
```

### 4. Giải bằng Integer Linear Programming (ILP)
```bash
python main.py -w 4 -g 3 -s 3 --method ilp
```

### 5. Xuất file DIMACS .cnf (không chạy solver)
```bash
python main.py -w 4 -g 3 -s 3 --export-dimacs output.cnf
```

### 6. Chạy toàn bộ Benchmark & Vẽ biểu đồ
```bash
python benchmarks/run_all.py
python benchmarks/plot_cns.py
```
