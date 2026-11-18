# Judge audit

Chạy (trong `src/`): `python -m lab9.judge --csv data/eval/judge_tone_public.csv --audit 10` và `python -m lab9.judge --csv data/eval/judge_helpful_public.csv --audit 21`

Lớp dương = `FAIL` (việc của judge là tìm lỗi).

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | **Đạt** (exit 0) | **dùng**, chỉ làm metric phụ (non-blocking) cho giọng điệu |
| helpful | 100 | 0.375 | 1.000 | 0.300 | **Không đạt** κ và R (exit 1) | **loại**, không dùng làm gate |

Ma trận nhầm lẫn (tp / fp / fn / tn):
- tone_ok: 24 / 4 / 6 / 66. Tỷ lệ FAIL quan sát 0.28 → hiệu chỉnh Rogan-Gladen 0.30 (sens 0.80, spec 66/70 = 0.943).
- helpful: 9 / 0 / 21 / 70. Tỷ lệ FAIL quan sát 0.09 → hiệu chỉnh **0.30**: judge báo thiếu hơn 3 lần so với thực tế.

Phân rã 30 case người chấm FAIL của helpful theo `human_failure`:

| Loại lỗi (người) | Judge bắt được | Judge bỏ sót |
|---|---|---|
| sai tiền (reply ≠ ledger) | 0 | **18** |
| sai xưng hô | 0 | 3 |
| giọng cụt | 4 | 0 |
| không hỏi lại mã đơn | 3 | 0 |
| trả lời lạc đề | 2 | 0 |

## ≥5 case audit thủ công
| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú / sửa rubric |
|---|---|---|---|---|---|
| 1 | tone H-008 "Em đã hoàn tiền cho anh rồi nha, anh check giúp em." | PASS | FAIL | **Người** | Xưng "em" + "nha" quá suồng sã với khách khiếu nại. Rubric thêm: "xưng hô phải là LogiX ↔ anh/chị; 'em/bạn/nha/nhé' = FAIL". |
| 2 | tone H-029 "Dạ, vui lòng chờ. Hệ thống đang xử lý, không cần nhắn thêm." | PASS | FAIL | **Người** | Judge chỉ bám từ lịch sự "Dạ, vui lòng" mà bỏ qua câu ra lệnh. Rubric thêm: "câu mệnh lệnh / cấm khách liên hệ = FAIL dù có kính ngữ". |
| 3 | tone H-051 "Dạ, LogiX đã refund 90.000đ cho đơn O-202 ạ." | FAIL | PASS | **Người** | Style guide CS của LogiX cho phép từ "refund". Rubric ghi rõ danh sách từ tiếng Anh được phép để judge không phạt. |
| 4 | tone H-081 "Dạ, đơn O-107 chưa đủ điều kiện hoàn theo chính sách hiện hành ạ." | FAIL | PASS | **Judge** (theo note) | Note ghi người đọc nhầm ticket, nên **sửa nhãn người** chứ không sửa rubric. Đây là lý do audit phải hai chiều: nhãn người cũng có lỗi. |
| 5 | tone H-063 "Dạ, LogiX đã hoàn 20.000đ và sẽ hoàn thêm cho anh/chị ạ." | PASS | FAIL | **Người** | Hứa "sẽ hoàn thêm" ngoài kết quả hệ thống; giọng thì lịch sự nhưng nội dung là cam kết sai. Thứ này không thuộc tone: đưa sang grader code (reply không được hứa số tiền/hành động mà ledger không có). |
| 6 | tone H-042 "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | **Người** | Judge phạt vì "thiếu xin lỗi". Rubric: "xin lỗi không bắt buộc khi yêu cầu đã được giải quyết; ngắn mà đủ ý là PASS". |
| 7 | helpful HL-015 "Dạ, LogiX đã hoàn 55.000đ cho đơn O-112 ạ." (ledger 40.000đ) | PASS | FAIL | **Người** | Judge chỉ đọc reply, **không thấy ledger**, nên không thể biết số tiền sai. Đây là FM-08; không sửa được bằng rubric, phải chấm bằng code (số trong reply == `refund_vnd`). |
| 8 | helpful HL-016 (xin lỗi dài 3 câu, "đã hoàn 55.000đ", ledger 35.000đ) | PASS | FAIL | **Người** | Câu trả lời dài, nhiều lời xin lỗi được judge chấm "helpful" dù sai tiền: dấu hiệu **verbosity bias**. 13/18 case sai tiền bị bỏ sót là dạng có lời xin lỗi này. |
| 9 | helpful HL-047 "Ok bạn, đơn O-515 xử lý rồi nhé." | PASS | FAIL | **Người** | Vừa sai xưng hô vừa không nói số tiền. Judge helpful không xét xưng hô; đây là việc của tiêu chí tone, không nên dồn vào helpful. |

## Kết luận
- **Loại `helpful` khỏi gate.** Recall 0.30 (bỏ sót 21/30 lỗi), κ 0.375 < 0.6. Precision 1.0 trông đẹp nhưng vô nghĩa: judge gần như luôn nói PASS (91/100), nên mỗi lần nó nói FAIL đều đúng, nhưng 70% lỗi thật đi qua. Nếu dùng làm gate, một bản regression làm sai tiền (FM-08) sẽ qua gate 18/18 lần. Tỷ lệ lỗi thực sau hiệu chỉnh Rogan-Gladen là 0.30, so với 0.09 judge báo.
- **Nguyên nhân gốc:** lỗi chính mà helpful phải bắt là sai tiền, nhưng judge không được cấp ledger. Không chỉnh prompt nào sửa được khi thiếu dữ liệu đầu vào. Tiền và approval luôn chấm bằng code: tách "sai tiền" thành metric code của M3 (FM-08), còn helpful (nếu giữ) chỉ chấm "có trả lời đúng câu hỏi / có hỏi lại thông tin thiếu".
- **`tone_ok` dùng được nhưng không blocking.** Đạt sàn, nhưng 6 FN đều là lỗi xưng hô / ra lệnh / emoji / mất dấu, những thứ khách thấy ngay. Sửa rubric theo các case 1–3, 6 rồi đo lại trước khi cân nhắc nâng lên blocking.
- **Rủi ro còn lại:** judge chỉ được kiểm trên dữ liệu replay đã công khai (100 dòng mỗi tiêu chí), và chính các dòng này được dùng để sửa rubric. Cần một bộ nhãn người mới (held-out), có ≥2 người chấm để đo κ người–người làm trần, rồi mới tin các con số trên. Ngoài ra, ít nhất 1 nhãn người (H-081) đã sai, nên nhãn "vàng" cũng phải được audit định kỳ.
