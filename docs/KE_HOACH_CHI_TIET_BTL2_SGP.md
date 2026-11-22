# HƯỚNG DẪN CÔNG VIỆC CHI TIẾT BTL2: SOCIAL GOLFER PROBLEM (SGP)
**Định dạng đầu ra:** Bài báo khoa học chuẩn Elsevier (`cas-sc`) | **Nhóm:** 3 thành viên (~33.3% mỗi người)  
**Nội dung nhóm chọn:** 4 cấu hình mô hình SAT one-hot ba chỉ số/Exactly-k (NSC, Sequential Counter, Totalizer, Cardinality Network), mở rộng Order Encoding, đối chiếu CP và ILP.
**Công cụ nhóm chọn:** PySAT, OR-Tools CP-SAT, Gurobi/MIP; dùng CNSPlots theo yêu cầu đề bài.

Đây là kế hoạch nội bộ. Đề bài yêu cầu thực nghiệm kích thước lớn, đối chiếu phương pháp chính xác, báo cáo khoa học theo Elsevier `cas-sc`, CNSPlots và link mã nguồn/kết quả trong Data Availability. PySAT, tên SAT solver và các encoding AMO là gợi ý/khuyến khích; đề không ấn định ma trận "6 encoders × 3 solvers × 4 SB".

**Quy ước:** bài SGP ghi instance theo `(g,p,w)`; API dự án dùng `(w,g,s)` với `s=p`. Ví dụ `2-2-3` trong bài nguồn là `solve_sgp(3,2,2)` và có nghiệm. Tên file `sat_direct_encoders.py` được giữ để tương thích, còn mô hình là one-hot ba chỉ số dựa trên basic constraints của NSE, không phải baseline DE bốn chỉ số của bài nguồn.

---

## TỔNG QUAN PHƯƠNG PHÁP & CÔNG CỤ CHỐT CHO ĐỀ TÀI

1. **4 cấu hình mô hình ba chỉ số theo mã nguồn `src/sat_direct_encoders.py`:**
   - C1 (mỗi người đúng một nhóm mỗi tuần): ALO + Pairwise AMO, giữ nguyên giữa các cấu hình.
   - C2 (mỗi nhóm đúng $s$ người, Exactly-k với $k=s$): so sánh **NSC** (`nsc`, mặc định), **Sequential Counter** (`seqcounter`), **Totalizer** (`totalizer`) và **Cardinality Network** (`cardnetwrk`). NSC tự cài đặt; ba bộ còn lại dùng PySAT `CardEnc.equals()`.
   - C3 (không gặp lại): giữ nguyên các mệnh đề Direct gồm 4 literal âm.
   - Mô hình one-hot ba chỉ số là mô hình chung của bốn cấu hình trên, không tính thành bộ mã hóa thứ năm độc lập. Đây là ablation của nhóm, chưa phải tái lập nguyên bộ thực nghiệm NSE/TME/SCE trong bài nguồn.
   - Order Encoding (`Order Encoding.pdf`) là phần mở rộng do TV3 phụ trách, chưa được triển khai trong mã nguồn hiện tại.
2. **2 Mô hình đối chứng chính xác:**
   - Constraint Programming (CP) giải bằng **Google OR-Tools CP-SAT**
   - Integer Linear Programming (ILP) giải bằng **Gurobi Optimizer** (hoặc OR-Tools MIP)
3. **SAT Solvers:** CaDiCaL 1.5.3 và Glucose 4.1 qua PySAT; cài bằng `requirements-sat.txt`.
4. **Symmetry Breaking:** bài nguồn có hai kỹ thuật chính: SB1 cố định tuần đầu và SB2 cố định người `i` vào nhóm `i` cho `i<=min(g,s)` ở các tuần sau. Những mở rộng về thứ tự nhóm/tuần phải có công thức và lập luận bảo toàn nghiệm riêng. Hiện SAT runner và pilot mặc định không thêm SB.
5. **Đồ họa khoa học:** Thư viện `cnsplots` (`https://cnsplots.farid.one/latest/`)
6. **Mẫu báo cáo:** Template LaTeX Elsevier `\documentclass[a4paper,fleqn]{cas-sc}` + Mục `Data Availability` dẫn link GitHub

**Lưu ý Exactly-k:** Các biến thể AMO của Binary, Commander và Product trong tài liệu học không dùng trực tiếp để thay C2 Exactly-$s$ tổng quát. Theo [tài liệu PySAT](https://pysathq.github.io/docs/html/api/card.html), `EncType.bitwise` hỗ trợ AMO; `EncType` không có `commander` hay `product`. Bộ so sánh C2 được chốt theo code là NSC/Sequential Counter/Totalizer/Cardinality Network.

---

# BẢNG PHÂN CHIA NHIỆM VỤ TỔNG QUAN

| Hạng mục | Thành viên 1 🔵 | Hướng (TV2) 🟢 | Thành viên 3 🟣 |
| :--- | :--- | :--- | :--- |
| **Đọc tài liệu** | • `Assignment 2 - req.pdf`<br>• `Mau bao cao 2DBMP.pdf` (Sec 1, 4)<br>• `6 - SGP.pdf` (Sec 1, 2)<br>• Docs OR-Tools CP & CNSPlots | • `Module 2 - SAT Encoding`<br>• `Module 3 - AMO ALO` (kiến thức nền)<br>• `6 - SGP.pdf` (mô hình Boolean, NSC, Eq. 2–9)<br>• Docs PySAT (CardEnc & Solvers), tài liệu Totalizer và Cardinality Network | • `Order Encoding.pdf` (Sec III-B)<br>• `6 - SGP.pdf` (Sec 2.2, 4.3.2, 4.4)<br>• `Mau bao cao 2DBMP.pdf` (Sec 2.1)<br>• `Module 4 - SAT Solvers` |
| **Cần Code những gì** | • `src/io_utils.py` (CLI & DIMACS)<br>• `src/verifier.py` (Universal Verifier)<br>• `src/display.py` (In ma trận lịch)<br>• `src/cp_solver.py` (OR-Tools CP)<br>• `benchmarks/plot_cns.py` (CNSPlots) | • `src/sat_direct_encoders.py` (Ánh xạ biến; C1 ALO + Pairwise AMO; C2 Exactly-s: NSC, SeqCounter, Totalizer, Cardinality Network; C3 Social)<br>• `src/sat_runner.py` (CaDiCaL, Glucose; kiểm chứng nghiệm)<br>• Dependency và hướng dẫn cài chạy | • `src/order_encoder.py` (Order Encoding)<br>• `src/ilp_solver.py` (Mô hình Gurobi/MIP)<br>• `src/symmetry.py` (SB1/SB2 nguồn, mở rộng có kiểm chứng)<br>• `benchmarks/run_all.py` (Benchmark suite) |
| **Viết Bài báo Elsevier** | • Abstract & Title<br>• Section 1: Introduction<br>• Section 2: CP Formulation<br>• Section 4: Computational Experiments<br>• Section 5: Conclusion & Data Avail. | • Section 3.1: Mô hình one-hot ba chỉ số theo NSE<br>• Section 3.2: Exactly-k Cardinality Encodings (NSC, SeqCounter, Totalizer, Cardinality Network; bảng số biến/clauses) | • Section 2: ILP Formulation<br>• Section 3.3: Order Encoding<br>• Section 3.4: SB1/SB2 nguồn và mở rộng có chứng minh |
| **Đầu ra khác** | Quản lý toàn bộ template LaTeX `cas-sc` | Quản lý phần SAT trên GitHub; dependency và README hướng dẫn cài chạy | Thiết kế Slide thuyết trình (15–20 trang), chuẩn bị kịch bản Demo |
| **TỶ LỆ KHỐI LƯỢNG** | **33.3%** | **33.3%** | **33.4%** |

---

# HƯỚNG DẪN CHI TIẾT CHO TỪNG THÀNH VIÊN

---

## 👤 THÀNH VIÊN 1 (TV1): Lead I/O, Solution Verifier, Mô hình CP, Vẽ CNSPlots & Báo cáo Elsevier

### 1. Đọc & Tìm hiểu những tài liệu nào?
1. **`Assignment 2 - requirements.pdf` (Trang 1 và 2):**
   - Nắm rõ yêu cầu so sánh SAT với CP (CP-SAT), yêu cầu bắt buộc dùng thư viện `cnsplots` để vẽ đồ thị, template LaTeX Elsevier `cas-sc`, và mục dẫn link GitHub `Data Availability`.
2. **`6 - Social Golfer Problem - SGP.pdf` (Section 1 và Section 2, Trang 1–4):**
   - Hiểu ký hiệu bài nguồn $(g,p,w)$ và quy đổi sang API $(w,g,s=p)$, tổng người $n=gs$ và các điều kiện nghiệm hợp lệ. Cận đối tác cần thiết là $w\le\lfloor(gs-1)/(s-1)\rfloor$ khi $s>1$; không áp dụng phép chia này khi $s=1$.
3. **`Mau xay dung bao cao BTL so 1 v BTL so 2.pdf` (Section 1 và Section 4):**
   - Xem cách các thầy viết Introduction chuẩn quốc tế và cách thiết kế bảng kết quả, biểu đồ so sánh với solver thương mại.
4. **Tài liệu Google OR-Tools CP-SAT (Python) & Thư viện `cnsplots`:**
   - Cách tạo biến nguyên, dùng hàm `AddAllDifferent()`, đo thời gian giải.
   - Cách dùng `cnsplots` vẽ Cactus plot và Line plot cho bài báo khoa học.

### 2. Cần Code những gì?
- **`src/io_utils.py`:**
  - Dự kiến viết bộ phân tích dòng lệnh (CLI parser) nhận các cờ: số tuần `-w`, số nhóm `-g`, số người mỗi nhóm `-s`, phương pháp `--method` (sat/order/cp/ilp), bộ mã hóa C2 `--amo` (nsc/seqcounter/totalizer/cardnetwrk; mặc định nsc), solver `--solver` (cadical/glucose), cấu hình `--sb` (none/sb1/full). `full` dự kiến chỉ gồm SB1/SB2 nguồn sau khi cài và kiểm chứng; các mở rộng có cờ riêng. Giữ tên cờ `--amo` theo giao diện dự kiến; giá trị chọn Exactly-$s$ cho C2. CLI chung hiện chưa được triển khai.
  - Kiểm tra cận đối tác khi $s>1$: nếu $w > \lfloor (gs-1)/(s-1) \rfloor$, báo UNSAT bằng precheck. Khi $s=1$, cận này không giới hạn số tuần. Cận là điều kiện cần, không phải điều kiện đủ.
  - Viết hàm xuất danh sách mệnh đề ra file text chuẩn định dạng DIMACS `.cnf`.
- **`src/display.py`:**
  - Viết hàm định dạng và in bảng lịch thi đấu ma trận theo từng tuần, từng nhóm rõ ràng, dễ nhìn.
- **`src/verifier.py` (Universal Solution Verifier):**
  - Viết thuật toán kiểm tra tính đúng đắn độc lập của lời giải thu được từ **bất kỳ solver nào** (SAT, CP hay ILP) qua 3 luật:
    1. *Mỗi tuần:* Mỗi người chơi đúng 1 lần (không ai vắng mặt, không ai chơi 2 lần).
    2. *Mỗi nhóm:* Đủ đúng $s$ người chơi.
    3. *Không gặp lại:* Mọi cặp người chơi gặp nhau trong cùng nhóm không quá 1 lần trong suốt $w$ tuần.
- **`src/cp_solver.py` (Mô hình Constraint Programming):**
  - Sử dụng Google OR-Tools CP-SAT (`ortools.sat.python.cp_model`):
    - Đặt biến số nguyên đại diện cho người chơi trong từng nhóm.
    - Áp dụng ràng buộc toàn cục `AddAllDifferent` cho mỗi tuần.
    - Áp dụng ràng buộc Social (số người trùng nhau giữa 2 nhóm ở 2 tuần khác nhau $\le 1$).
    - Giải, trích xuất và kiểm chứng nghiệm; ghi riêng thời gian xây dựng mô hình, wall time solve và toàn quá trình. Chỉ ghi CPU time khi đo được, không thay bằng wall time.
- **`benchmarks/plot_cns.py` (Vẽ đồ thị CNSPlots):**
  - Đọc `results.csv` theo [chuẩn CSV benchmark v1](#5-chuẩn-csv-benchmark-v1), dùng `cnsplots` vẽ:
    - **Cactus Plot:** So sánh số bài toán giải được theo thời gian giữa SAT (Cadical), CP (CP-SAT), và ILP (Gurobi).
    - **Runtime Line Plot:** So sánh thời gian chạy của 4 bộ mã hóa C2 Exactly-$s$ (NSC, Sequential Counter, Totalizer, Cardinality Network) khi số người $n$ tăng dần; giữ C1, C3, solver và cấu hình SB giống nhau.
    - **Bar Plot:** So sánh hiệu năng Direct Encoding vs. Order Encoding.

### 3. Viết những phần nào trong Bài báo Elsevier (`cas-sc`)?
- **Abstract & Title:** Tóm tắt mục tiêu, phương pháp (4 cấu hình SAT Direct/Exactly-k, Order Encoding nếu đã triển khai, CP và ILP), và các kết quả thực nghiệm đạt được.
- **Section 1: Introduction:** Nêu bối cảnh bài toán SGP, ứng dụng thực tế (xếp lịch hội thảo, thi đấu), cấu trúc bài báo và tóm tắt đóng góp.
- **Section 2: Background (Phần CP):** Mô tả toán học mô hình Constraint Programming và sức mạnh của ràng buộc toàn cục `AllDifferent`.
- **Section 4: Computational Experiments:** Lập bảng số liệu kết quả, chèn các hình vẽ từ `cnsplots`, phân tích so sánh đối đầu giữa SAT, CP và ILP.
- **Section 5: Conclusion & Data Availability:** Tóm tắt kết luận, đánh giá hạn chế, nêu hướng phát triển và dẫn link GitHub chứa mã nguồn.

---

## 👤 THÀNH VIÊN 2 (TV2) - Hướng: Mô hình SAT ba chỉ số, Exactly-s và runner SAT

**Phạm vi:** phụ trách C1/C2/C3, bốn cấu hình Exactly-s, tích hợp SAT solver,
dependency, hướng dẫn sử dụng và phần SAT của báo cáo. Order Encoding, CP,
ILP, triển khai symmetry breaking và benchmark chung thuộc các phần việc khác.

### 1. Đọc & Tìm hiểu những tài liệu nào?

1. **`Assignment 2 - requirements.pdf`:** nắm yêu cầu thực nghiệm, so sánh
   phương pháp chính xác, báo cáo `cas-sc`, CNSPlots và Data Availability.
2. **`6 - Social Golfer Problem - SGP.pdf`:** đọc mô hình Boolean ba chỉ số,
   C1/C2/C3, NSC và Eq. (2)-(9); phân biệt mô hình này với DE bốn chỉ số.
3. **`Module2_SAT Encoding.pdf` và `Module3_AMO ALO Encoding.pdf`:** nắm
   DIMACS, ALO, AMO, Exactly-one và Exactly-k. Binary/Commander/Product dạng
   AMO là kiến thức nền, không phải bốn cấu hình C2 được giao trong dự án.
4. **Tài liệu PySAT:** `CardEnc.equals`, `EncType.seqcounter`,
   `EncType.totalizer`, `EncType.cardnetwrk`; giao diện `Solver`,
   `Cadical153`, `Glucose4`.
5. **Mẫu báo cáo BTL:** cách trình bày mô hình, số biến/mệnh đề và giao thức
   thực nghiệm; dùng chung template `cas-sc` do TV1 quản lý.

### 2. Cần Code những gì?

- **`src/sat_direct_encoders.py`:**
  - Ánh xạ `var(i,j,k,g,w)` và `decode_var(var_id,g,w)`, với chỉ số người,
    nhóm, tuần bắt đầu từ 0 và DIMACS bắt đầu từ 1:
    $$\mathrm{ID}(i,j,k)=i\cdot g\cdot w+j\cdot w+k+1.$$
  - C1: mỗi người đúng một nhóm mỗi tuần, dùng ALO + pairwise AMO cố định.
  - C2: mỗi nhóm đúng $s$ người. So sánh đúng bốn cấu hình:
    1. `nsc`: tự cài NSC trong `encode_c2_nsc()` theo Eq. (2)-(9).
    2. `seqcounter`: `CardEnc.equals(..., encoding=EncType.seqcounter)`.
    3. `totalizer`: `CardEnc.equals(..., encoding=EncType.totalizer)`.
    4. `cardnetwrk`: `CardEnc.equals(..., encoding=EncType.cardnetwrk)`.
  - C3: mỗi cặp người cùng nhóm nhiều nhất một lần, dùng các clause bốn
    literal âm; giữ nguyên C1 và C3 khi thay đổi cấu hình C2.
  - `encode_sgp(w,g,s,encoding='nsc',symmetry_clauses=None)` trả
    `(clauses, num_vars, stats)`. Biến phụ không trùng biến chính hay nhau.
  - Nhận clause symmetry dùng ID biến chính từ TV3; không tự thêm SB.
  - `extract_schedule()` giải mã model đầy đủ; `format_schedule()` định dạng
    lịch. Schedule dùng `schedule[week][group] -> list[player]`, chỉ số 0-based.

- **`src/sat_runner.py`:**
  - `solve_cnf()` giải CNF đã có; `solve_sgp()` sinh CNF, giải và kiểm chứng lịch.
  - Mỗi lần gọi chọn **một** solver: `cadical` = CaDiCaL 1.5.3,
    `glucose` = Glucose 4.1.
  - Cô lập backend trong subprocess, giới hạn thời gian và phân biệt
    `SAT`, `UNSAT`, `TIMEOUT`, `UNAVAILABLE`, `ERROR`.
  - Kiểm tra model thỏa CNF và lịch thỏa C1/C2/C3; SAT hợp lệ có
    `model_verified=True`, `verified=True` và `schedule`.
  - Ghi riêng thời gian sinh CNF, backend wall time, solve-only wall time,
    CPU time và toàn quá trình; thống kê native chỉ ghi khi có dữ liệu.
  - Dùng cận đối tác làm precheck khi $s>1$; với $s=1$ không áp dụng cận này.
    Cận chỉ là điều kiện cần. Precheck UNSAT không gọi solver.
  - Cung cấp CLI `python -m src.sat_runner`; không phụ thuộc `main.py`
    hay các module của TV1/TV3 để chạy phần SAT.

- **Dependency và bàn giao GitHub:**
  - Duy trì `requirements-sat.txt`, tích hợp vào `requirements.txt` và viết
    README ngắn về cài đặt, CLI, API, tham số và định dạng kết quả.
  - Dùng PySAT upstream trên Python 3.10 trở lên, không cần wheel native riêng.
  - Phần bàn giao gồm code SAT, dependency và hướng dẫn.
  - Comment chỉ mô tả ngắn chức năng của file/hàm; công thức và phần lý thuyết
    chi tiết đặt trong tài liệu hoặc báo cáo.

### 3. Viết những phần nào trong Bài báo Elsevier (`cas-sc`)?

- **Section 3.1: Mô hình SAT one-hot ba chỉ số:** định nghĩa biến, ánh xạ
  DIMACS và công thức C1/C2/C3; dùng đúng ký hiệu $(w,g,s)$ và quy đổi
  nhãn nguồn $(g,p,w)$ với $s=p$.
- **Section 3.2: Exactly-k Cardinality Encodings:** trình bày NSC,
  Sequential Counter, Totalizer và Cardinality Network cho C2 với $k=s$;
  nêu cách đếm biến chính, biến phụ và mệnh đề. C1/C3 được giữ cố định.
- Cung cấp mô tả cấu hình SAT, phiên bản solver và cách đo thời gian cho
  TV1/TV3 ghép vào phần thực nghiệm. Bài chung vẫn cần CP/ILP, Order Encoding,
  biểu đồ CNSPlots và Data Availability theo phân công.

---

## 👤 THÀNH VIÊN 3 (TV3): Chuyên gia Order Encoding, Mô hình ILP, Symmetry Breaking & Benchmark

### 1. Đọc & Tìm hiểu những tài liệu nào?
1. **`Order Encoding.pdf` (Trọng tâm - Section III-B, Trang 5–6):**
   - Bài báo của Thầy (TS. Tô Văn Khánh) về Order Encoding: Nắm vững nguyên lý biến trật tự: Biến nguyên $X \in [1..D]$ biểu diễn qua chuỗi biến Boolean $B_{X \le v}$. Mối quan hệ tự nhiên: $X \le v \to X \le v+1$.
2. **`6 - Social Golfer Problem - SGP.pdf` (Section 2.2 trang 4; Section 4.3.2 trang 12–13):**
   - Phân biệt đối xứng người, nhóm và tuần; bài nguồn mô tả không gian lịch bằng biểu thức xấp xỉ $(n!)^w/((s!)^{gw}(g!)^w w!)$, không khẳng định có $(n!)^w$ cấu hình tương đương.
   - Hiểu đúng SB1/SB2 trong Eq. (11)–(12). Section 4.4 trang 13–14 là phân tích độ phức tạp, không trình bày bốn SB.
3. **`Mau xay dung bao cao BTL so 1 v BTL so 2.pdf` (Section 2.1, Trang 4–5):**
   - Nắm cách xây dựng mô hình Quy hoạch tuyến tính nguyên (ILP) dạng chuẩn toán học: biến quyết định, hàm mục tiêu, hệ ràng buộc tuyến tính.
4. **`Module4_Design of SAT solver.pdf` (Trang 15–20):**
   - Hiểu cơ chế học mệnh đề từ xung đột (CDCL) để giải thích lý do tại sao không gian đối xứng làm chậm solver và tại sao SB giúp tăng tốc.

### 2. Cần Code những gì?
- **`src/order_encoder.py` (Mã hóa Order Encoding):**
  - Xây dựng mô hình biến nguyên: $P_{w, g, c} \in [1 \dots n]$ là golfer thứ $c$ của nhóm $g$ tại tuần $w$.
  - Định nghĩa biến Boolean trật tự: $B_{w, g, c, v} \iff (P_{w, g, c} \le v)$ với $v \in [1 \dots n-1]$.
  - Sinh các mệnh đề trật tự cơ sở: $[\neg B_{w, g, c, v}, B_{w, g, c, v+1}]$.
  - Bảo đảm mọi vị trí trong cùng tuần chứa đủ mỗi người đúng một lần (AllDifferent trên $n$ vị trí), ngoài các ràng buộc social.
  - Nếu chọn thứ tự tăng trong nhóm, với $X=P_{w,g,c}$ và $Y=P_{w,g,c+1}$, mã hóa $X<Y$ bằng $[\neg B_{Y\le v},B_{X\le v-1}]$ cho $1\le v\le n$, quy ước $B_{X\le0}=\bot$, $B_{Y\le n}=\top$. Các biên cho $\neg B_{Y\le1}$ và $B_{X\le n-1}$. Phải kiểm chứng phép mã hóa strict này; công thức ngược chiều không biểu diễn $X<Y$.
  - Sinh các mệnh đề cấm trùng cặp qua các tuần.
- **`src/ilp_solver.py` (Mô hình Quy hoạch tuyến tính nguyên ILP):**
  - Mô hình hóa SGP bằng Gurobi (`gurobipy`) hoặc OR-Tools Linear Solver:
    - Biến nhị phân: $x_{i,j,k} \in \{0, 1\}$.
    - Ràng buộc: Mỗi người đúng 1 nhóm/tuần; Mỗi nhóm đúng $s$ người.
    - Dùng biến $0\le y_{i_1,i_2,j,k}\le1$ biểu diễn hai người cùng nhóm: $y\ge x_{i_1,j,k}+x_{i_2,j,k}-1$, $y\le x_{i_1,j,k}$ và $y\le x_{i_2,j,k}$. Với mỗi cặp người, đặt $\sum_{k=1}^{w}\sum_{j=1}^{g}y_{i_1,i_2,j,k}\le1$; không cho phép $y$ âm để bù các lần gặp.
    - Giải bài toán và ghi nhận thời gian thực thi của ILP solver.
- **`src/symmetry.py` (SB nguồn và mở rộng được kiểm chứng):**
  - Ưu tiên hai kỹ thuật của bài nguồn, có cờ bật/tắt riêng:
    1. `SB1`: Cố định tuần 1 (gán cứng golfer $i$ vào nhóm $\lceil i/s \rceil$ bằng Unit Clauses).
    2. `SB2`: Với tuần sau tuần đầu, gán người $i$ vào nhóm $i$ cho $1\le i\le\min(g,s)$, theo Eq. (12).
  - Thứ tự nhóm/tuần là các hướng mở rộng, không gán thành SB3/SB4 của bài nguồn. Với biểu diễn membership ba chỉ số, người trong nhóm vốn không có chỉ số vị trí. Mỗi mở rộng hoặc tổ hợp SB cần lập luận bảo toàn ít nhất một nghiệm trong mỗi lớp đối xứng và kiểm tra trên oracle nhỏ trước khi dùng.
- **`benchmarks/run_all.py` (Benchmark Suite tự động):**
  - Dùng `benchmarks/benchmark_instances.csv` chứa 66 instance tham khảo và các ca biên bổ sung; quy đổi đúng `(g,p,w)` sang `(w,g,s)`. Chọn phạm vi/tài nguyên thực nghiệm công khai, không mặc định một dải tham số nhỏ đã đại diện cho bài nguồn.
  - Với SAT Direct, đo 4 bộ mã hóa C2 (`nsc`, `seqcounter`, `totalizer`, `cardnetwrk`) $\times$ các SAT solver khả dụng $\times$ cấu hình SB; giữ C1 và C3 cố định. Chạy Order Encoding khi đã triển khai; chạy CP và ILP thành các cấu hình đối chứng riêng trên cùng bộ test và giới hạn thời gian.
  - Xuất `benchmarks/results.csv` đúng [chuẩn CSV benchmark v1](#5-chuẩn-csv-benchmark-v1) cho TV1.

### 3. Viết những phần nào trong Bài báo Elsevier (`cas-sc`) & Slide?
- **Section 2: Background (Phần ILP Formulation):** Mô tả toán học mô hình ILP cho SGP và kỹ thuật tuyến tính hóa tích biến nhị phân qua biến phụ.
- **Section 3.3: Order Encoding for SGP:** Mô tả nguyên lý Order Encoding và giải thích ưu thế duy trì tính lan truyền suy diễn (Unit Propagation) trên quan hệ thứ tự.
- **Section 3.4: Symmetry Breaking Constraints:** Phân tích đối xứng người/nhóm/tuần, trình bày SB1/SB2 nguồn; mô tả riêng nguồn và chứng minh của các mở rộng thực sự được triển khai.
- **Slide thuyết trình (15–20 trang):** Thiết kế slide theo chuẩn hội nghị khoa học và chuẩn bị terminal sẵn sàng demo trực tiếp tốc độ giải của các solver.

---

## 4. TIẾN ĐỘ THỰC HIỆN 6 TUẦN

- **Tuần 1:** Cả nhóm đọc đúng các phần tài liệu được giao. Họp cuối tuần 1 để chốt hiểu biết lý thuyết và tạo Git repo.
- **Tuần 2:** Thiết kế công thức toán học trên giấy. TV1 nháp Section 1; TV2 lập bảng biến, C1 ALO + Pairwise AMO và công thức 4 bộ mã hóa C2 Exactly-k; TV3 lập công thức Order Encoding và mô hình ILP.
- **Tuần 3 (Sprint Code 1):** TV1 code `io_utils.py`, `verifier.py`; TV2 hoàn thiện và kiểm chứng `sat_direct_encoders.py` (NSC, Sequential Counter, Totalizer, Cardinality Network); TV3 code `symmetry.py`, `ilp_solver.py`.
- **Tuần 4 (Sprint Code 2):** TV1 code `cp_solver.py`; TV2 hoàn thiện `sat_runner.py`; TV3 code `order_encoder.py` và `run_all.py`. **Mốc M3: Chạy thành công SGP(2,2,2) và SGP(3,3,3) trên cả SAT, CP, ILP!**
- **Tuần 5 (Thực nghiệm):** TV3 chạy `run_all.py` xuất `results.csv`; TV1 dùng `cnsplots` vẽ toàn bộ biểu đồ; TV2 hoàn thiện code SAT và giữ mô tả ngắn cho file/hàm.
- **Tuần 6 (Báo cáo & Thuyết trình):** Cả nhóm ráp bài báo LaTeX `cas-sc`; TV2 hoàn thiện README GitHub; TV3 hoàn thiện Slide và kịch bản Demo; tập dượt thuyết trình và nộp bài.

---

## 5. Chuẩn CSV benchmark v1

Dùng một định dạng `results.csv` để so sánh SAT Direct, Order Encoding, CP-SAT và ILP. Mỗi dòng ghi kết quả của một bài với một tổ hợp **phương pháp, encoder và solver**. Cấu hình cố định của đợt đo như SB, cutoff, số luồng, phiên bản solver và máy chạy ghi một lần trong phần thiết lập thực nghiệm. Dùng UTF-8, dấu phẩy và dấu chấm thập phân.

```csv
instance,n,method,encoding,solver,status,encode_time_seconds,solver_wall_time_seconds,total_time_seconds,num_vars,num_clauses,num_constraints,error
```

| Cột | Ý nghĩa |
| --- | --- |
| `instance` | Nhãn SGP theo `g-s-w`. Ví dụ `2-2-3` là 2 nhóm, mỗi nhóm 2 người, chơi 3 tuần. |
| `n` | Tổng số người, bằng `g*s`. Dùng làm trục ngang khi vẽ theo kích thước bài. |
| `method` | Phương pháp `sat`, `order`, `cp` hoặc `ilp`. |
| `encoding` | SAT dùng `nsc`, `seqcounter`, `totalizer` hoặc `cardnetwrk`; Order ghi `order`; CP/ILP để trống. |
| `solver` | Backend đã chọn, ví dụ `cadical`, `glucose`, `cp-sat` hoặc `gurobi`. Dùng một cột này cho mọi phương pháp. |
| `status` | `SAT` khi lịch đã được kiểm chứng; `UNSAT` khi solver kết luận vô nghiệm; `UNSAT_PRECHECK` khi loại bằng cận đối tác. Giữ riêng `TIMEOUT`, `SKIPPED_RESOURCE_LIMIT`, `UNAVAILABLE` và `ERROR`. |
| `encode_time_seconds` | Giây sinh CNF cho SAT/Order hoặc dựng mô hình cho CP/ILP. |
| `solver_wall_time_seconds` | Giây solver thực sự giải sau khi dựng mô hình. |
| `total_time_seconds` | Giây từ trước bước precheck/dựng đến khi có kết quả đã kiểm chứng hoặc hết giờ. Bao gồm nạp dữ liệu vào solver và kiểm chứng. |
| `num_vars` | Tổng số biến của CNF hoặc mô hình đã dựng, trước khi giải. |
| `num_clauses` | Số mệnh đề của CNF, dành cho SAT/Order. |
| `num_constraints` | Số ràng buộc của mô hình CP/ILP. |
| `error` | Lý do ngắn khi lỗi, hết giờ, thiếu solver hoặc bỏ qua. Lượt bình thường để trống. |

Ví dụ minh họa cách ghi, các thời gian bên dưới là số ví dụ:

```csv
2-2-3,4,sat,nsc,cadical,SAT,0.001,0.002,0.015,54,210,,
2-2-3,4,cp,,cp-sat,SAT,0.004,0.010,0.016,54,,66,
2-2-4,4,sat,nsc,cadical,UNSAT_PRECHECK,,,0.001,,,,
```

**Quy tắc ghi và vẽ.** Nếu chưa dựng/giải như ở `UNSAT_PRECHECK`, để trống số đo và kích thước tương ứng. `0` chỉ khi đo hoặc đếm được bằng 0. `num_clauses` và `num_constraints` là hai loại số đếm riêng. Khi dùng cùng một cấu hình chạy, khóa mỗi dòng theo `(instance, method, encoding, solver)`. Nếu thử lại, chỉ lấy một kết quả theo quy tắc của đợt đo. TV1 dùng `total_time_seconds` với cùng tập bài và cutoff để so sánh. Tách precheck khỏi số bài solver giải được.

**Trước đợt đo lại.** TV3 cập nhật bộ ghi, TV1 cập nhật bộ đọc biểu đồ, TV2 kiểm tra nhánh SAT và số mệnh đề/biến. Chạy trước `2-2-3` (SAT), `2-3-2` (UNSAT do solver), `2-2-4` (UNSAT do cận) và một ca timeout để kiểm tra trạng thái, ô trống và cách đếm. Các lượt chính bắt đầu bằng file mới đúng header trên.

Benchmark so sánh mặc định dùng SB `none`, một luồng và giới hạn 60 giây từ lúc trước dựng đến khi kiểm chứng xong. Worker nạp thư viện và khởi tạo giấy phép Gurobi trước khi tính giờ. Các lượt đặt riêng `--timeout` dùng giới hạn của từng backend và phục vụ khảo sát.

Nhóm cử một thành viên chạy `benchmarks.run_all` và chia sẻ một file `results.csv` cho cả nhóm. Người chạy giữ `results.csv.meta.json` cạnh CSV trên máy để `--resume` kiểm tra SB, số luồng và giới hạn thời gian. Dùng file đầu ra mới khi đổi các thiết lập này hoặc khi CSV cũ chưa có metadata. Ca thử lại trong cùng cấu hình thay đúng dòng cũ.

Khi chỉ nhận `results.csv` của đợt đo mặc định, dùng `--cutoff 60` để vẽ biểu đồ. Đường thời gian C2 tính trung bình trên những bài cùng được các encoder giải trong cutoff cho từng kích thước. Cactus so sánh SAT, CP và ILP trên những bài cả ba phương pháp đều đã thử.
