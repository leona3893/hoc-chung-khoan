# Bot phân tích và tín hiệu

Ba script, chạy bằng Python chuẩn (không cần `pip install`):

| Script | Làm gì | Chạy khi nào |
| --- | --- | --- |
| `fetch_ssi.py` | Tải giá từ SSI iBoard, tính chỉ báo, chấm điểm → `data/analysis.json`, `data/bars/` | Sau mỗi phiên |
| `signals.py` | So bảng điểm phiên mới với phiên trước, tìm những gì vừa đổi → `data/signals.json` + gửi Telegram | Ngay sau `fetch_ssi.py` |
| `backtest.py` | Chạy lại bộ luật trên 5 năm quá khứ → `data/backtest.json` | Khi sửa luật, hoặc hằng tuần |
| `telegram_setup.py` | Lấy chat id và gửi thử một tin | Một lần, khi bật Telegram |

```bash
python scripts/fetch_ssi.py          # bảng điểm
python scripts/signals.py            # tín hiệu (cần chạy ít nhất 2 phiên mới có gì để so)
python scripts/backtest.py           # kiểm chứng, ~3 phút lần đầu, sau đó vài giây nhờ cache
```

GitHub Actions đã chạy sẵn hai việc đầu vào 16:30 giờ Việt Nam các ngày trong tuần
([update-data.yml](../.github/workflows/update-data.yml)) và backtest chiều thứ Bảy
([backtest.yml](../.github/workflows/backtest.yml)).

---

## Bot này làm gì và không làm gì

**Có**: quét 34 mã sau mỗi phiên, phát hiện mã vừa đổi bậc khuyến nghị, vừa lùi về vùng mua,
vừa mất điểm cắt lỗ hoặc đạt mục tiêu của kế hoạch phiên trước, vừa xuất hiện setup kỹ thuật
(MA20 cắt MA50, bứt phá kèm khối lượng, test lại MA20, khối lượng đột biến), và khi trạng thái
thị trường đổi. Gửi cho bạn qua Telegram, đồng thời ghi file cho trang web đọc.

**Không**: không đặt lệnh, không kết nối tài khoản chứng khoán, không giữ khoá API giao dịch nào.
Repo này là trang tĩnh trên GitHub Pages — bất cứ khoá nào để ở đây đều là khoá công khai.

**Vì sao dừng ở mức báo tín hiệu**: xem `data/backtest.json` hoặc mục 07 của trang phân tích.
Trong 5 năm gần nhất, không một biến thể nào của bộ luật này thắng được việc mua và giữ VN-Index.
Tự động hoá một bộ luật chưa chứng minh được kỳ vọng dương chỉ làm bạn mất tiền nhanh hơn và
đều hơn. Khi nào backtest cho thấy lợi thế thật, thêm phần đặt lệnh mới có nghĩa.

---

## Bật thông báo Telegram

1. Mở Telegram, nhắn cho [@BotFather](https://t.me/BotFather): `/newbot`, đặt tên. Nó trả về một
   **token** dạng `8123456789:AAH...`.
2. Nhắn một câu bất kỳ cho bot vừa tạo (bot không gửi được tin cho người chưa từng nhắn nó).
3. Lấy **chat id** — chạy ở terminal trên máy bạn, không phải nhắn vào Telegram:

   ```bash
   python scripts/telegram_setup.py 8123456789:AAH...
   ```

   Script kiểm tra token, đọc tin bạn vừa nhắn ở bước 2, in ra chat id và gửi thử một tin
   để bạn biết đường truyền đã thông. Token không bị ghi vào file nào.

   (Nếu muốn tự làm tay: `curl "https://api.telegram.org/bot<TOKEN>/getUpdates"` rồi tìm
   `"chat":{"id":123456789`. Lưu ý trong PowerShell, `curl` là alias của `Invoke-WebRequest`
   nên cú pháp khác — dùng Git Bash hoặc `curl.exe` nếu gọi tay.)

4. Thử gửi một tín hiệu thật ở máy:

   ```powershell
   $env:TELEGRAM_BOT_TOKEN="..."
   $env:TELEGRAM_CHAT_ID="..."
   python scripts/signals.py --force
   ```

   Muốn xem trước nội dung tin mà không gửi: `python scripts/signals.py --dry`

5. Để Actions gửi hộ: trong repo trên GitHub → **Settings → Secrets and variables → Actions →
   New repository secret**, thêm `TELEGRAM_BOT_TOKEN` và `TELEGRAM_CHAT_ID`.

Không có hai secret đó thì workflow vẫn chạy bình thường, chỉ là không gửi tin — trang web vẫn
hiển thị tín hiệu ở mục 02.

---

## Mức độ tín hiệu

| Mức | Nghĩa | Gồm những gì |
| --- | --- | --- |
| **Cần xem ngay** | Trạng thái đổi theo hướng cần hành động | Lên MUA, chuyển BÁN, mất điểm cắt lỗ, thị trường đổi trạng thái |
| **Đáng biết** | Thay đổi có ý nghĩa nhưng chưa cấp | Nâng/hạ bậc khác, đạt mục tiêu, lùi về vùng mua với lời/lỗ ≥ 1,5, bứt phá, MA20 cắt MA50 |
| **Ghi nhận** | Chỉ để theo dõi | Test lại MA20, khối lượng đột biến, lùi về vùng mua nhưng lời/lỗ dưới 1,5 |

Bot chỉ báo cái **vừa đổi**, nên phần lớn các phiên sẽ rất ít hoặc không có tín hiệu. Đó là
trạng thái đúng — không phải lỗi.

---

## Backtest: đọc kết quả thế nào

`backtest.py` mô phỏng đúng những gì một người dùng thật làm được:

- Điểm của phiên `t` chỉ dùng dữ liệu tới hết phiên `t` (không nhìn trước).
- Lệnh khớp ở **giá mở cửa phiên `t+1`**, cộng trượt giá 0,15%.
- Phí mua 0,15%, phí bán 0,15%, thuế bán 0,1%.
- **T+2**: mua phiên `t` thì sớm nhất bán được phiên `t+2`.
- Lô 100, rủi ro 1% vốn mỗi lệnh, tối đa 5 vị thế, một mã không quá 25% vốn.
- Bỏ qua lệnh nếu giá mở cửa cao hơn giá tín hiệu quá 4% (không mua đuổi).

Mười biến thể vào/thoát lệnh được chạy song song trên cùng dữ liệu, so với mua và giữ VN-Index.
Sửa giả định ở `COST` và `RULES` đầu file, thêm biến thể ở danh sách `variants` trong `main()`.

Con số đáng nhìn là **R trung bình mỗi lệnh**, không phải tỷ lệ thắng. Tỷ lệ thắng 60% mà R
trung bình bằng 0 nghĩa là lệnh thắng nhỏ hơn lệnh thua — đúng vấn đề của bộ luật hiện tại.

### Những gì backtest này *không* chứng minh được

- Thành phần khối ngoại (±10 điểm) bị bỏ: API SSI chỉ cho dữ liệu mua/bán ròng khoảng một tháng.
- Rổ mã là VN30 **hiện tại** → có thiên lệch người sống sót, kết quả quá khứ bị tô hồng.
- Giá chưa chắc đã điều chỉnh cổ tức và chia tách (tuỳ nguồn).
- Không mô phỏng được việc không khớp đủ khối lượng ở mã thanh khoản thấp.

---

## Sửa bộ luật

Toàn bộ điểm nằm trong `analyze()` của `fetch_ssi.py`, bảy thành phần có ghi chú rõ từng mức
điểm. Sau khi sửa:

```bash
python scripts/backtest.py --refresh    # bắt buộc: cache điểm cũ không còn đúng
```

So R trung bình trước và sau. Nếu không cải thiện, đừng giữ thay đổi đó — kể cả khi nó "nghe
hợp lý hơn".
