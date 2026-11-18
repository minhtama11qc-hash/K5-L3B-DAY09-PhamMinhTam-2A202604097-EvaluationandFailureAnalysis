# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-014 --seed 11
python -m lab9.trace_case --shape fixed --claim C-014 --seed 11   # đối chứng
```

## Case: `seeded_regression` C-014@11 — trừ tiền hai lần rồi báo sai số cho khách

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-014@11`, item `E-014`, report `E-seeded_regression-20261118-988e` (`src/reports/eval_seeded_regression.json`); trace run `R-seeded_regression-C-014-s11` |
| Triệu chứng | Lab 8 grader FAIL `proposal_mismatch`. `refund_amount_correct` = False: **ledger 90.000đ**, nhãn 120.000đ. `reply_matches_ledger` = False: reply "Dạ, LogiX đã hoàn **120.000đ** cho đơn O-515." trong khi ledger ghi 90.000đ. Khách bị hoàn thiếu 30.000đ **và** được báo sai số. Lặp lại trên cả 5 seed (E-014 fail 5/5). |
| Bước sai đầu tiên | **Event 5 `proposal`** `{"amount_vnd": 120000}`: agent tự lấy quote 150.000 trừ `refunded_vnd` 30.000 trước khi gọi host. |
| Vì sao là bước *đầu tiên* | Event 1 `handoff` đúng hợp đồng (scope `owner_order_only`). Event 2 `investigator` đọc đúng O-515 (`delivered_late`). Event 3 `quote` 150.000, clause `SHIP-LATE-03` + `DMG-04`, đúng như `fixed`. Event 4 `refund_history` `{"refund_count": 1, "refunded_vnd": 30000}` là dữ liệu thật, đọc không sai. Event 5 là chỗ đầu tiên agent **biến đổi** số tiền; host `issue_refund` vốn đã trừ phần đã hoàn, nên khoản 30.000 bị trừ lần hai ⇒ ledger 90.000. Event 6 `reply` sai theo (báo số tự tính 120.000), nhưng chỉ là hệ quả. |
| Failure mode | **FM-05** pre_deducted (gốc), kéo theo **FM-08** misreport ở reply. Xem `docs/failure_taxonomy.md` (anchor A3). |
| Đối chứng | `fixed C-014@11`: event 1–3 giống hệt; **không có** event `refund_history` / `proposal`; agent gửi nguyên quote 150.000 cho host, host trừ 30.000 ⇒ ledger 120.000 = nhãn; event 4 `reply` "đã hoàn 120.000đ" khớp ledger. Lab 8 grader PASS. |
| Regression test | `src/tests/test_lab9_trace_case.py` (marker `student`, chạy trong job `eval-gate`). `test_lab9_trace_case_seeded_regression_is_caught`: chạy lại trial, assert `proposal` đứng ngay sau `refund_history` với 120.000, ledger 90.000, `RefundAmountCorrect` = False, `ReplyMatchesLedger` = False. `test_lab9_trace_case_fixed_control_passes`: cùng claim@seed trên `fixed` không có `proposal`, ledger 120.000, cả hai grader pass. **Đã chạy:** fail-detected trên variant lỗi, pass trên `fixed` (21/21 test học viên xanh). Ở mức gate: `reply_matches_ledger` 0.786 và `refund_amount_correct` 0.857 đều BLOCK trên `seeded_regression`. |
| Chưa chắc chắn | Trace không ghi lời gọi `issue_refund` và phần host tự trừ: "host trừ lần hai" được suy ra từ ledger (90.000 = 120.000 − 30.000) và từ code `lab9/variant_agent.py`, không phải từ một event. Trace cũng không cho biết model *vì sao* trừ (prompt hay logic); với MockLLM đây là công tắc gài sẵn, trên model thật cần event ghi lý do. Chỉ 1 claim (C-014) có refund trước đó mà vẫn được hoàn, nên FM-05 ở dạng "hoàn thiếu" chỉ có 1 item trong eval set v1. |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
