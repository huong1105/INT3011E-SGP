# Bộ instance tham chiếu từ bài SGP

`sgp_paper_instances.csv` chứa đủ **66 instance khác nhau** trong **Table 10, trang PDF 31–32** của bản thảo *An Efficient SAT Encoding for Solving the Social Golfer Problem*, Tuyen Van Kieu, Nguyen Tan Nguyen và Khanh Van To. File nguồn trong dự án là `6 - Social Golfer Problem - SGP.pdf`.

Các hàng được giữ theo thứ tự Table 10: 33 hàng ở trang 31, 33 hàng ở trang 32. Dữ liệu đã được trích từ hai trang và đối chiếu lại nhãn, tham số, trạng thái và số trang. Việc đọc CSV khi chạy chương trình hoặc kiểm thử không cần thư viện PDF.

## Ý nghĩa các cột

| Cột | Ý nghĩa |
| --- | --- |
| `paper_label` | Nhãn gốc `g-p-w` trong bài nguồn. |
| `g` | Số nhóm mỗi tuần. |
| `s` | Số người mỗi nhóm, tương ứng với `p` trong bài nguồn. |
| `w` | Số tuần. |
| `source_status` | Trạng thái tham chiếu từ cột `Res` của Table 10, đã chuẩn hóa. |
| `source_pdf_page` | Số trang PDF, bắt đầu từ 1; ở bản nguồn này trùng số trang in. |

Quy ước trạng thái nguồn:

- `S` → `SAT`: 41 instance.
- `U` → `UNSAT`: 15 instance.
- `-` → `UNKNOWN`: 10 instance.

Đây là **kết quả được nguồn báo cáo**, không phải số đo mới của mã nguồn trong dự án. `UNKNOWN` chỉ phản ánh trạng thái chưa xác định trong bảng nguồn tại thời điểm thực nghiệm; không có nghĩa bài toán vô nghiệm hoặc còn mở về mặt toán học hiện nay. File này không chép thời gian, số biến hoặc số mệnh đề của tác giả thành kết quả của nhóm.

## Đổi thứ tự tham số

Bài nguồn dùng `(g, p, w)`, còn API dự án dùng `(w, g, s)` với `s = p`. Vì vậy:

- Nhãn nguồn `6-3-8` tương ứng `encode_sgp(8, 6, 3)`.
- Ví dụ `2-2-3` ở trang 4 tương ứng `encode_sgp(3, 2, 2)`. Ví dụ này không nằm trong 66 hàng của Table 10.

Khi đọc CSV, dùng tên cột để tránh truyền nhầm thứ tự:

```python
import csv

with open("data/sgp_paper_instances.csv", encoding="utf-8", newline="") as stream:
    instances = list(csv.DictReader(stream))

row = instances[0]
api_parameters = (int(row["w"]), int(row["g"]), int(row["s"]))
```

CSV này là danh mục cho thực nghiệm sau; việc có đủ 66 hàng không đồng nghĩa đã chạy benchmark 66 bài. Các bài lớn không được tự động giải trong unit tests. Kiểm thử tính đúng đắn dùng một oracle tổ hợp độc lập trên các bài nhỏ trong `tests/test_sgp_oracle.py`.
