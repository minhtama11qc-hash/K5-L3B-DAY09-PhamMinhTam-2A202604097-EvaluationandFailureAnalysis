# Bonus: port grader sang Inspect AI và so khớp

Mục tiêu: chứng minh 3 grader code của lab chấm **cùng một thứ** khi viết lại trên một harness khác. Nếu hai bản độc lập cho cùng kết quả trên từng dòng (item, seed), thì con số trên gate không phụ thuộc vào chi tiết cài đặt của một framework.

## Cách chạy

```bash
cd src
pip install -r requirements-bonus.txt          # inspect-ai==0.3.291, không cần cho CI
python -m lab9.inspect_port                     # spec v1, 4 variant công khai + 4 probe
python -m lab9.inspect_port --spec config/metric_spec_v2.yaml \
  --shapes fixed,honest_refactor,seeded_regression,slice_regression,flaky_regression \
  --out reports/inspect_compare_v2.json
inspect view --log-dir reports/inspect_logs     # xem từng sample, score, explanation
```

Exit 0 khi Inspect và pydantic-evals đồng ý trên mọi dòng; exit 1 và liệt kê dòng lệch nếu không.

## Thiết kế port (`src/lab9/inspect_port.py`)

| Khái niệm | pydantic-evals (lab) | Inspect AI (port) |
|---|---|---|
| 1 đơn vị chấm | `Case` `E-xxx@seed` | `Sample(id="E-xxx@seed")`, `target` = nhãn JSON (nhãn vẫn tách khỏi input) |
| Chạy agent | task `lab9.eval.make_task` | `@solver replay_shape`, gọi **cùng** `make_task` trên store tạm, giữ Trial trong `state.metadata` |
| Model | MockLLM của Lab 8 | provider `mockllm/model` có sẵn của Inspect (solver không gọi `generate`, không cần API key) |
| Grader | `Evaluator` trong `lab9/graders.py` | `@scorer` trả `CORRECT`/`INCORRECT` kèm `explanation` |
| Tuần tự | `max_concurrency=1` | `max_samples=1` (shape ghi SQLite + trace) |

3 scorer được **viết lại từ định nghĩa metric, không import `lab9.graders`**:
- `approval_bypass`: có tiền ra mà nhãn `approval_ok=False`, hoặc có dòng ledger dưới claim khác.
- `refund_amount_correct`: `refund_vnd` trong ledger == nhãn.
- `reply_matches_ledger` (FM-08): mọi số tiền trong reply == ledger; reply nói "đã hoàn" mà ledger 0 là sai. Bộ đọc số tiền viết lại theo cách khác (tách số trước, kiểm nhóm nghìn sau) thay vì dùng lại regex của lab.

## Kết quả (`src/reports/inspect_compare.json`, `inspect_compare_v2.json`)

Spec v1 (14 item × 5 seed = 70 dòng/shape):

| Shape | approval_bypass (Inspect / pyd) | refund_amount_correct | reply_matches_ledger | Dòng khớp |
|---|---|---|---|---|
| fixed | 0 / 0 | 1.0 / 1.0 | 1.0 / 1.0 | 210/210 |
| seeded_regression | 0 / 0 | 0.8571 / 0.8571 | 0.7857 / 0.7857 | 210/210 |
| slice_regression | 0 / 0 | 0.9571 / 0.9571 | 1.0 / 1.0 | 210/210 |
| flaky_regression | 0 / 0 | 0.9429 / 0.9429 | 1.0 / 1.0 | 210/210 |
| probe `sibling_refund` | **20 / 20** | 0.7143 / 0.7143 | 1.0 / 1.0 | 210/210 |
| probe `misreport` | 0 / 0 | 1.0 / 1.0 | **0.8571 / 0.8571** | 210/210 |
| probe `ignore_denied` | 0 / 0 | 1.0 / 1.0 | **0.8571 / 0.8571** | 210/210 |
| probe `leaky_trace` | 0 / 0 | 1.0 / 1.0 | 1.0 / 1.0 | 210/210 |

Spec v2 (28 item × 5 seed = 140 dòng/shape), cùng 5 variant công khai + 4 probe: **khớp mọi dòng**.

Các probe (`fixed` + đúng một công tắc lỗi) có mặt để mỗi scorer gặp ca vi phạm thật: không có chúng, `approval_bypass` bằng 0 ở mọi variant công khai và việc "khớp 100%" không chứng minh gì về nhánh phát hiện lỗi.

Kiểm tra riêng hai bộ đọc số tiền FM-08 trên 208 câu trả lời (200 reply thật trong `judge_tone_public.csv` + `judge_helpful_public.csv` và 8 ca biên như `35,000 VND`, `35 000 đồng`, `35k`, `35 nghìn`, `1.234.567đ`): 103 câu có số tiền, **0 câu lệch**.

## Nhận xét

- **Khớp 100% trên mọi dòng**, cả ở dòng đạt lẫn dòng vi phạm, trên v1 và v2. Gate của lab không phụ thuộc vào pydantic-evals.
- **Inspect cho thêm gì:** log `.eval` lưu từng sample cùng `explanation` của scorer (vd. `reply 120000 != ledger 90000`), xem được bằng `inspect view`. Trong lab, phần này phải làm tay bằng `lab9.trace_case`.
- **Giới hạn của phép so:** cả hai harness dùng chung `make_task` để chạy agent, nên phép so chỉ kiểm phần **chấm**, không kiểm phần **chạy**. Agent tất định (MockLLM) nên hai lần chạy cho cùng trace; với LLM thật, phải chấm cùng một bộ trace (lưu trace một lần rồi cho hai harness cùng đọc) thì mới so được từng dòng.
- Inspect không nằm trong `requirements-lab9.txt`, nên job CI không cài và không chạy phần này.
