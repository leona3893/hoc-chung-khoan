# Bot phân tích và tín hiệu

Ba script, chạy bằng Python chuẩn (không cần `pip install`):

| Script | Làm gì | Chạy khi nào |
| --- | --- | --- |
| `scan.py` | **Tầng 1** — quét cả sàn (VNALL + HNX30), lọc thanh khoản, chấm điểm nhanh → `data/scan.json` + shortlist | Sau mỗi phiên |
| `fetch_ssi.py` | **Tầng 2** — chấm điểm đầy đủ cho VN30 + mã tay + shortlist → `data/analysis.json`, `data/bars/` | Sau `scan.py` |
| `ideas.py` | **Tầng 3** — mở ý tưởng khi có điểm buy, theo dõi tới điểm sell → `data/ideas.json` | Sau `signals.py` |
| `signals.py` | So bảng điểm phiên mới với phiên trước, tìm những gì vừa đổi → `data/signals.json` + gửi Telegram | Ngay sau `fetch_ssi.py` |
| `backtest.py` | Chạy lại bộ luật trên 5 năm quá khứ → `data/backtest.json` | Khi sửa luật, hoặc hằng tuần |
| `crypto.py` | Khung chiến lược crypto: nhiều chiến lược cắm vào một bộ máy, backtest nến Binance/OKX | Khi thêm hoặc sửa chiến lược |
| `crypto_bot.py` | Bot tín hiệu crypto: quét sàn mỗi nến 4h, ra điểm mua, theo dõi, ra điểm bán | Mỗi 4 giờ, 24/7 |
| `crypto_chart.py` | Vẽ ảnh chart kèm mỗi tín hiệu (cần Pillow) | Bot tự gọi |
| `morning.py` | Nhắc trước giờ mở cửa: hôm nay cần đặt lệnh gì, đang giữ gì, cắt lỗ ở đâu | 8:50 mỗi ngày |
| `intraday.py` | Canh giá so với ngưỡng của kế hoạch phiên trước, nhắn Telegram | Mỗi 30 phút trong phiên |
| `telegram_setup.py` | Lấy chat id và gửi thử một tin | Một lần, khi bật Telegram |

```bash
python scripts/scan.py               # quét sàn, ~4 phút cho 342 mã
python scripts/fetch_ssi.py          # bảng điểm đầy đủ cho rổ chính + shortlist
python scripts/signals.py            # tín hiệu (cần ít nhất 2 phiên mới có gì để so)
python scripts/ideas.py              # sổ theo dõi: điểm buy → theo dõi → điểm sell
python scripts/intraday.py           # cảnh báo trong phiên (chạy trong giờ giao dịch)
python scripts/backtest.py           # kiểm chứng rổ chính
python scripts/backtest.py --universe scan   # kiểm chứng rổ quét sàn
```

## Ba tầng, đúng thứ tự

```
   scan.py          342 mã  →  lọc thanh khoản  →  162 mã có điểm  →  shortlist ~40 mã
      ↓
   fetch_ssi.py     chấm lại đầy đủ shortlist + VN30: có khối ngoại, hỗ trợ/kháng cự,
                    và KẾ HOẠCH GIÁ (vùng mua, cắt lỗ, mục tiêu, lời/lỗ)
      ↓
   signals.py       so với phiên trước → cái gì vừa đổi
   ideas.py         mã đạt MUA → mở ý tưởng → khớp giá mở cửa phiên sau → theo dõi
                    từng phiên → ĐIỂM SELL khi chạm cắt lỗ / mục tiêu / bị hạ bậc / hết hạn
      ↓
   intraday.py      trong phiên: canh ngưỡng giá của kế hoạch, nhắn ngay khi chạm
```

GitHub Actions đã chạy sẵn: bảng điểm + tín hiệu lúc 16:30 giờ Việt Nam các ngày trong tuần
([update-data.yml](../.github/workflows/update-data.yml)), cảnh báo trong phiên mỗi 30 phút
([intraday.yml](../.github/workflows/intraday.yml)), và backtest chiều thứ Bảy
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

## Quét sàn

`scan.py` lấy rổ **VNALL** (toàn bộ cổ phiếu HOSE trong rổ VNAllShare, 312 mã) cộng **HNX30**.
UPCoM không có API nhóm công khai — và cũng là nơi screen kỹ thuật ít đáng tin nhất vì thanh
khoản quá mỏng; cần thì thêm tay vào `extra` trong `watchlist.json`.

Hai cái lọc trước khi chấm điểm:

- **Thanh khoản**: giá trị khớp trung bình 20 phiên ≥ 3 tỷ/phiên (`scan_min_value_20d`).
  Dưới mức đó bạn không vào ra được mà không tự đẩy giá. Lọc này loại khoảng 180/342 mã.
- **Đủ lịch sử**: ≥ 150 phiên, để MA50 và biên 52 tuần có nghĩa.

Điểm trong `scan.json` **không có thành phần khối ngoại** (±10) — lấy dữ liệu khối ngoại cho 342
mã là 342 request nữa, không đáng. Mã vào shortlist được `fetch_ssi.py` chấm lại đầy đủ.

Đổi rổ, ngưỡng thanh khoản hay độ dài shortlist ở `watchlist.json`:
`scan_groups`, `scan_min_value_20d`, `scan_min_sessions`, `scan_shortlist`.

---

## Sổ theo dõi ý tưởng

`ideas.py` là phần trả lời câu "ra điểm buy rồi thì sao nữa". Vòng đời một ý tưởng:

| Phiên | Việc xảy ra |
| --- | --- |
| t | Mã đạt mức **MUA** → ghi ý tưởng, trạng thái *chờ khớp* |
| t+1 | Khớp ở **giá mở cửa**. Mở cửa cao hơn giá tín hiệu quá 4% thì **bỏ**, không mua đuổi |
| mỗi phiên | Chạm cắt lỗ → ĐIỂM SELL · chạm mục tiêu → ĐIỂM SELL · bị hạ bậc xuống GIẢM/BÁN → ĐIỂM SELL · giữ quá 40 phiên → ĐIỂM SELL |

Tối đa 5 ý tưởng mở cùng lúc, đúng như backtest. Nhờ vậy **thành tích sống so được thẳng với
thành tích backtest** — lệch nhiều và kéo dài là dấu hiệu bộ luật đang mất tác dụng, không phải
vận xấu.

### Bẫy điều chỉnh giá — đã xử lý

Cổ phiếu Việt Nam trả cổ tức bằng cổ phiếu rất thường xuyên, và chuỗi giá bị **điều chỉnh hồi
tố**: giá quá khứ bị hạ xuống. Hậu quả nếu không chặn: kế hoạch cũ (cắt lỗ 25.631) đem so với
giá mới đã điều chỉnh (22.700) trông y như một cú sập xuyên cắt lỗ, và bot báo "mất cắt lỗ" trong
khi thực tế không ai mất gì.

Biên độ một phiên của HOSE là ±7%, HNX ±10%. Nên cả ba script đều coi mức rơi **hơn 12% trong
một phiên** là dấu hiệu điều chỉnh giá, và xử lý riêng: `signals.py` báo "chuỗi giá vừa bị điều
chỉnh" rồi bỏ hết so sánh ngưỡng của mã đó trong phiên; `ideas.py` đóng ý tưởng với lý do
"điều chỉnh cổ tức" và không ghi nhận R giả; `intraday.py` cũng vậy.

---

## Một ngày của bot

| Giờ VN | Script | Gửi gì | Ghi repo |
| --- | --- | --- | --- |
| **8:50** | `morning.py` | Nhắc việc cần làm hôm nay: lệnh chờ đặt, mã đang giữ và mức cắt lỗ của từng mã | Không |
| 9:20 → 14:35, mỗi 30 phút | `intraday.py` | Chỉ khi có mã chạm ngưỡng: mất cắt lỗ, giảm sàn, vào vùng mua, chạm mục tiêu | Không |
| **16:30** | `scan.py` → `fetch_ssi.py` → `signals.py` → `ideas.py` | Hai tin: cái gì vừa đổi, và điểm buy/sell của sổ theo dõi | Có |
| 17:00 thứ Bảy | `backtest.py` | Không nhắn | Có |

Nhịp này khớp với cách hệ thống hoạt động: nến ngày đóng lúc 14:45 nên **16:30 mới là lúc
điểm đáng tin**; bạn đọc buổi tối, nghĩ lúc không có giá nhấp nháy, rồi **đặt lệnh sáng hôm sau**
— đúng như `ideas.py` và backtest đều giả định (khớp ở giá mở cửa phiên sau). Tin 8:50 tồn tại
vì qua một đêm thì dễ quên mất mình định làm gì.

`morning.py` không gọi API giá và không tính lại gì — chỉ đọc `ideas.json` và `analysis.json`
nên không bao giờ sai vì nến chưa đóng. Không có gì đang mở hoặc chờ khớp thì nó im lặng
(`--force` để gửi cả khi trống). Nó cũng không biết ngày nghỉ lễ: hôm đó tin vẫn tới nhưng
không có gì phải làm vì phiên 16:30 trước đó không tạo ý tưởng mới.

---

## Cảnh báo trong phiên

`intraday.py` chạy mỗi 30 phút từ 9:15 đến 14:45 và **không chấm điểm lại**. Nó chỉ so giá khớp
hiện tại với bốn ngưỡng đã cố định từ phiên trước:

| Ngưỡng | Khi nào nhắn |
| --- | --- |
| Mất cắt lỗ | Giá khớp xuống dưới `plan.stop` |
| Giảm sàn | Giá khớp bằng hoặc dưới giá sàn |
| Vào vùng mua | Giá lùi về trong 1,5% quanh `plan.entryLo` |
| Chạm mục tiêu | Giá khớp đạt `plan.target` |

Chỉ xét những mã phiên trước được khuyến nghị **MUA** hoặc **TÍCH LŨY** — mã đã bị hạ bậc thì
tín hiệu cuối phiên đã nói rồi, không cần nhắc lại trong phiên.

**Vì sao không chấm điểm lại giữa phiên**: điểm được tính từ MA20/50/200, RSI 14, MACD trên giá
đóng cửa ngày. Chấm lúc 10h là chấm trên một cây nến chưa đóng — 10h ra MUA, 14h ra THEO DÕI,
ATC lại đổi lần nữa. Đó là nhiễu, không phải tín hiệu. Ngưỡng giá thì khác: nó là một con số cố
định, so với giá hiện tại lúc nào cũng đúng.

Mỗi ngưỡng chỉ nhắn **một lần mỗi phiên**. Trạng thái "đã nhắn gì" nằm trong
`data/cache/intraday-state.json`, lưu qua Actions cache nên **không commit gì vào repo**. Gửi
thất bại thì không ghi trạng thái, lần chạy sau nhắn lại.

```bash
python scripts/intraday.py --dry      # xem trước, không gửi, không ghi trạng thái
python scripts/intraday.py --force    # bỏ qua kiểm tra giờ và phiên, để thử ngoài giờ
python scripts/intraday.py --reset    # xoá trạng thái, cho nhắn lại từ đầu
```

Hai giới hạn phải biết: cron của GitHub Actions **thường trễ 5–15 phút** khi GitHub tải cao, nên
đừng dùng nó để canh lệnh theo từng phút; và nếu repo không có hoạt động nào trong 60 ngày,
GitHub tự tạm dừng các workflow theo lịch. Muốn chính xác tới giây thì phải có tiến trình chạy
liên tục ở máy bạn hoặc VPS — với hệ thống giữ trung bình 12 phiên thì không cần.

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

### Hai rổ, hai kết quả khác nhau

| | Rổ chính (33 mã VN30) | Rổ quét sàn (159 mã) |
| --- | --- | --- |
| Chỉ MUA, chốt ở kháng cự | +11,2% · R tb +0,032 | −15,9% · R tb −0,084 |
| MUA + TÍCH LŨY | +13,4% · R tb +0,110 | −9,0% · R tb +0,062 |
| **MUA, không chốt lời cứng** | −9,5% · R tb −0,022 | **+14,8% · R tb +0,538** |
| Mua và giữ VN-Index | +27,7% · sụt 40,3% | +27,7% · sụt 40,3% |

Đọc được hai điều:

1. **Mục tiêu đặt ở kháng cự gần nhất là chỗ rò rỉ lớn nhất.** Trên rổ rộng, bỏ chốt lời cứng
   làm R trung bình nhảy từ −0,08 lên **+0,54**: lệnh thắng trung bình 3,34R so với lệnh lỗ
   0,91R. Thắng chỉ 34% số lệnh nhưng tổng vẫn dương — đúng hình dạng của một hệ thống theo
   xu hướng.
2. **Nhưng vẫn chưa thắng mua-và-giữ về lợi nhuận tuyệt đối** (+14,8% so với +27,7% trong 5
   năm), chỉ hơn ở mức sụt vốn (−23,0% so với −40,3%). Lý do R cao mà lãi không cao: với lệnh
   có cắt lỗ sát, quy mô 1% rủi ro đòi hỏi vị thế lớn hơn giới hạn 25% vốn một mã, nên số tiền
   thật trên mỗi R nhỏ hơn 1%.

**Cảnh báo về chính con số +0,538R**: nó là cái tốt nhất trong 11 biến thể chạy trên *cùng* một
đoạn dữ liệu. Chọn ra cái tốt nhất sau khi đã thấy kết quả thì luôn đẹp hơn thực tế. Muốn tin
nó thì phải kiểm tra ngoài mẫu — ví dụ tính riêng 2021–2023 rồi áp sang 2024–2026 — hoặc theo
dõi sổ ý tưởng chạy tiến về phía trước đủ lâu. Đừng đổi luật chỉ vì một con số đẹp.

### Những gì backtest này *không* chứng minh được

- Thành phần khối ngoại (±10 điểm) bị bỏ: API SSI chỉ cho dữ liệu mua/bán ròng khoảng một tháng.
- Rổ mã là VN30 / VNAllShare **hiện tại** → có thiên lệch người sống sót, kết quả quá khứ bị tô hồng.
- Biến thể tốt nhất được chọn sau khi xem kết quả của cả 11 biến thể trên cùng dữ liệu, nên
  lợi thế của nó bị thổi lên. Chưa có kiểm tra ngoài mẫu.
- Giá chưa chắc đã điều chỉnh cổ tức và chia tách (tuỳ nguồn).
- Không mô phỏng được việc không khớp đủ khối lượng ở mã thanh khoản thấp.

---

## Khung chiến lược crypto

`crypto.py` là bộ máy riêng cho crypto, tách đúng ba phần như mọi bot tín hiệu nên làm:

```
[ ĐIỀU KIỆN VÀO ]   mỗi chiến lược là một hàm ~15 dòng trong STRATEGIES
[ KHỐI THOÁT LỆNH ] cắt lỗ / chốt lời / trailing / giữ tối đa — dùng chung
[ MÔ PHỎNG + BÁO ]  phí, trượt giá, trần vị thế, thống kê R — dùng chung
```

Thêm một chiến lược = viết một hàm `def s_xyz(x, i, p)` trả về True/False rồi khai báo trong
`STRATEGIES`. Mọi thứ còn lại dùng lại được ngay.

```bash
python scripts/crypto.py --list                 # danh sách chiến lược
python scripts/crypto.py --pairs 30 --months 36 # backtest đủ, ~6 phút
python scripts/crypto.py --strategy vcr         # chạy một cái
```

Năm chiến lược có sẵn, trong đó hai cái dựng lại từ một kênh tín hiệu công khai (`vcr` =
xả mạnh kèm khối lượng đột biến, `rsi_vol_gated` = RSI quá bán kèm khối lượng), dùng đúng khối
thoát lệnh mà kênh đó in trên chart: SL 5% / TP 10% / trailing 7% / giữ tối đa 72 giờ.

### Kết quả: cả năm đều lỗ nặng

30 cặp USDT thanh khoản nhất, nến 1h, 13/10/2023 → 13/10/2026 (26.300 nến), phí 0,1% mỗi chiều
+ trượt giá 0,05%:

| Chiến lược | Lệnh | Thắng | R trung bình | Lãi cả kỳ |
| --- | --- | --- | --- | --- |
| vcr (bắt đáy theo khối lượng) | 1.371 | 34,9% | −0,085 | −77,6% |
| rsi_vol_gated (RSI quá bán) | 1.240 | 34,4% | −0,187 | −92,2% |
| ma_cross (theo xu hướng) | 2.352 | 33,3% | −0,157 | −98,0% |
| breakout | 3.196 | 34,3% | −0,107 | −97,8% |
| bb_bounce | 3.290 | 34,7% | −0,137 | −99,3% |
| **Mua và giữ BTC** | — | — | — | **+212,5%** |

Bốn phép kiểm chứng để chắc đây không phải lỗi mô phỏng:

1. **Vào lệnh ngẫu nhiên** với cùng khối thoát lệnh cho R trung bình **−0,067** — tức `vcr`
   (−0,085) và `rsi_vol_gated` (−0,187) đều **tệ hơn vào lệnh bừa**. Điều kiện vào không những
   không có lợi thế, nó còn chọn đúng lúc xấu.
2. **Bỏ hết phí**: `vcr` lên −0,028R, `rsi_vol_gated` lên −0,128R — vẫn âm. Phí chịu khoảng
   0,06R mỗi lệnh (0,3% vòng mua-bán chia cho cắt lỗ 5%), phần còn lại là do chính tín hiệu.
3. **Tách theo chế độ thị trường**: `vcr` đạt −0,02R khi BTC dưới MA200 ngày và −0,16R khi BTC
   trên MA200 — không có chế độ nào cứu được nó.
4. **Quét tham số**: 12 tổ hợp ngưỡng rơi × bội số khối lượng cho `vcr` đều âm (−0,047 đến
   −0,164R); bốn ngưỡng RSI đều âm; nới cắt lỗ lên 8–12% vẫn âm. Kết luận không phụ thuộc vào
   con số nào cụ thể.

Nguyên nhân gộp lại: tỷ lệ 2:1 (TP 10% / SL 5%) cần thắng trên 33% mới hoà **trước phí**. Cả
năm chiến lược đều quanh 33–35%, tức đúng mức hoà vốn — rồi phí nhân với 1.300–3.300 lệnh kéo
tất cả xuống. Giao dịch khung 1h với tần suất này thì **phí là đối thủ lớn nhất**, không phải
thị trường.

### Những gì kết quả này không chứng minh

- Tham số thật của kênh tín hiệu kia có thể khác bản dựng lại (ngưỡng rơi, bộ lọc cặp, có lọc
  xu hướng BTC hay không). Hình dạng chiến lược thì chắc, con số cụ thể thì không.
- Rổ cặp là những cặp thanh khoản nhất **hôm nay** — thiên lệch người sống sót rất nặng với
  crypto. Kết quả thật nhiều khả năng còn tệ hơn, không khá hơn.
- Nến 1h không cho biết trong một nến giá chạm cắt lỗ trước hay chốt lời trước; ở đây luôn giả
  định chạm cắt lỗ trước.

## Bot tín hiệu crypto

`crypto_bot.py` là bản crypto của sổ theo dõi ý tưởng: quét các cặp thanh khoản nhất mỗi khi
nến 4h đóng, mở **vị thế giấy** khi một chiến lược bắt được tín hiệu, rồi theo dõi tới khi
chạm cắt lỗ / chốt lời / trailing / hết hạn giữ và báo điểm bán kèm PnL và số R.

```bash
python scripts/crypto_bot.py --dry       # xem trước, không ghi, không gửi
python scripts/crypto_bot.py             # chạy thật
python scripts/crypto_bot.py --reset     # xoá sổ
```

Cấu hình ở `CFG` đầu file: khung nến, số cặp quét, số vị thế tối đa, và **danh sách chiến lược
chạy song song** (mặc định `vcr` + `rsi_vol_gated`). Khối thoát lệnh lấy thẳng từ `crypto.py`
nên backtest và bot luôn dùng chung một bộ luật.

GitHub Actions chạy lúc 00:06, 04:06, 08:06, 12:06, 16:06, 20:06 UTC
([crypto-bot.yml](../.github/workflows/crypto-bot.yml)) — sáu phút sau mỗi lần nến 4h đóng.
Sổ ghi vào `data/crypto-ideas.json` và chỉ commit khi có thay đổi.

### Ảnh chart kèm tín hiệu

Mỗi tin mua/bán gửi kèm một ảnh PNG do `crypto_chart.py` vẽ: 70 nến gần nhất, MA14, vùng chốt
lời xanh và vùng cắt lỗ đỏ kéo từ nến vào lệnh, **đường cắt lỗ dời bậc thang**, mốc MUA/BÁN,
khung khối lượng kèm ngưỡng ×2,5. Tin nhắn đi kèm làm chú thích ảnh, ngắn gọn:

```
🟢 MUA W/USDT
Vào: 0.00931
Cắt lỗ: 0.008844 (−5%)
Chốt lời: 0.010241 (+10%)
Trailing 7% · Giữ tối đa 72h
Chiến lược: vcr (−0,012R/lệnh khi backtest)
⚠️ Sổ giấy, không phải khuyến nghị.
```

Pillow là **thư viện ngoài duy nhất** của cả repo, và chỉ dùng cho việc vẽ này. Không có nó
thì bot vẫn chạy bình thường, chỉ gửi chữ (`--no-chart` để tắt hẳn). Gửi ảnh dùng `sendPhoto`
với multipart tự dựng bằng `urllib`, không thêm thư viện nào.

Xem thử một ảnh mẫu: `python scripts/crypto_chart.py BTCUSDT 4h`

**Gửi thử một tin thật** — kiểm tra token Telegram và đường gửi ảnh mà không phải chờ tín hiệu:

```bash
python scripts/crypto_bot.py --test BTC                 # một mã
python scripts/crypto_bot.py --test ltc,ada,avax,dot   # nhiều mã một lần
python scripts/crypto_bot.py --test BTC --dry          # chỉ in ra, không gửi
```

Trên GitHub: **Actions → Bot tín hiệu crypto → Run workflow**, điền mã vào ô *test* (vd `BTC`).
Để trống ô đó thì nó quét thật như bình thường. Lần chạy thử không ghi gì vào sổ.

### Lọc token cổ phiếu

Binance niêm yết khoảng 90 cổ phiếu và ETF Mỹ token hoá, đặt tên bằng mã chứng khoán cộng chữ
"B" (`AAPLB`, `TSLAB`, `NVDAB`, `SPYB`, `SNDKB`…). Giá của chúng bám cổ phiếu cơ sở nên chiến
lược crypto áp lên đó là so sai thị trường — lần quét thử đầu tiên đã ra tín hiệu mua `SNDKB`
(SanDisk) trước khi phát hiện. Giờ lọc theo quy tắc đặt tên, trừ vài coin thật cũng kết thúc
bằng B (`SHIB`, `BNB`); gặp mã mới thì thêm vào `NOT_STOCK` trong `crypto.py`.

### Nguồn dữ liệu dự phòng

Binance trả **HTTP 451** cho một số vùng, trong đó có dải IP của GitHub Actions. Nên cả
`crypto.py` lẫn `crypto_bot.py` tự chuyển sang **OKX** khi gặp 451 — cùng dữ liệu nến, khác
định dạng, đã kiểm tra chạy được cho cả danh sách cặp lẫn lịch sử giá.

### Bot này không đặt lệnh

Không có khoá API sàn ở bất kỳ đâu trong repo. Nếu sau này bạn muốn nó đặt lệnh thật, phần đó
**phải** chạy ở máy bạn hoặc VPS với khoá trong `.env` không commit — không bao giờ để trên
GitHub Actions của một repo công khai.

Và trước khi nghĩ tới chuyện đó: đọc lại bảng kết quả backtest ở trên. Năm chiến lược, hai
khung thời gian, ba năm dữ liệu, tất cả đều âm. Bot này có giá trị như **một cái máy ghi chép
chạy tiến về phía trước** để đối chiếu với backtest — không phải như một nguồn thu nhập.

## Sửa bộ luật

Toàn bộ điểm nằm trong `analyze()` của `fetch_ssi.py`, bảy thành phần có ghi chú rõ từng mức
điểm. Sau khi sửa:

```bash
python scripts/backtest.py --refresh    # bắt buộc: cache điểm cũ không còn đúng
```

So R trung bình trước và sau. Nếu không cải thiện, đừng giữ thay đổi đó — kể cả khi nó "nghe
hợp lý hơn".

## Đặt lệnh thật cho bot xu hướng

`exchange.py` cho `trend_bot.py` tự đặt lệnh trên Binance Spot. **Mặc định tắt**, chỉ chạy khi
có biến `LIVE_TRADING=testnet` hoặc `LIVE_TRADING=live`. GitHub Actions không đặt biến này
nên trên Actions bot vẫn chỉ ghi sổ giấy.

Sổ giấy vẫn là nơi ra quyết định, file này chỉ làm theo:

| Sổ giấy | Tài khoản thật |
| --- | --- |
| Mở lệnh trong nến ngày hôm nay | Mua `capital / maxOpen` USDT (mặc định 30) bằng lệnh market |
| Đóng lệnh theo luật | Bán đúng số coin **bot đã mua**, không đụng coin bạn có sẵn |
| Lệnh giấy mở từ hôm trước (bot bật giữa chừng) | Không mua — không vào lệnh trễ |
| Không còn lệnh đó (sổ bị reset) | **Không tự bán**, chỉ nhắn bạn |

### Chốt tay không làm rối bot

Bạn bán tay trên app Binance lúc nào cũng được. Mỗi lần chạy, bot so số dư trên sàn với số coin
nó đã mua. Nếu thấy hụt, nó tìm lệnh bán của bạn để lấy giá, ghi vào sổ là *chốt tay* kèm
lời/lỗ, rồi thôi theo dõi lệnh đó. Bot **không mua lại** mã đó cho tới khi sổ giấy ra một tín
hiệu mới. Bán một phần cũng được: phần còn lại bot vẫn giữ và bán theo luật.

Lý do không bao giờ bị kẹt:

- Bot **không đặt lệnh chờ** (cắt lỗ/chốt lời) trên sàn, nên coin không bị khoá. Luật thoát tính
  trên nến ngày đóng, đúng như backtest.
- Bot **không huỷ hay sửa lệnh của bạn**. Nếu bạn đặt lệnh chốt lời chờ mà luật bảo bán, bot chỉ
  nhắn rằng coin đang khoá trong lệnh của bạn.
- Mã lệnh của bot cố định theo từng lệnh giấy (`tb-BTCUSDT-<ngày>-B`), nên chạy lại hay chạy trùng
  cũng không mua hai lần.

Một giới hạn: nếu bạn **đã có sẵn** đúng coin đó, bot không phân biệt được bạn đang bán coin
của mình hay của nó. Nó coi phần của nó vẫn còn chừng nào số dư còn đủ. Muốn rạch ròi thì tạo
một **sub-account** riêng cho bot.

### Bật lên

1. **Testnet trước.** Vào <https://testnet.binance.vision>, đăng nhập GitHub, *Generate HMAC_SHA256 Key*.
   Tiền ảo có sẵn. Lưu ý: giá testnet lệch giá thật, và testnet thỉnh thoảng bị reset — khi đó
   bot báo "số dư biến mất" và đóng lệnh.
2. Đặt biến môi trường rồi kiểm tra:

   ```bash
   export LIVE_TRADING=testnet BINANCE_API_KEY=... BINANCE_API_SECRET=...
   python scripts/exchange.py check     # số dư, quyền của key
   python scripts/trend_bot.py --dry    # xem bot định mua/bán gì, không đặt lệnh
   python scripts/trend_bot.py          # chạy thật
   python scripts/exchange.py status    # lệnh bot đang giữ, lời/lỗ
   ```

3. **Tiền thật** chỉ khi testnet chạy êm vài tuần. Tạo key trên Binance chỉ bật *Spot Trading*,
   **tắt Withdrawals**, khoá theo IP của VPS. Bot **từ chối đặt lệnh** nếu key có quyền rút tiền.
   Đổi `LIVE_TRADING=live`.

Sổ thật nằm ở `data/cache/live-trend.json` (không commit). Trên VPS nên trỏ cả hai sổ ra ngoài
repo để `git pull` không đụng file mà Actions đang commit:

```bash
export TREND_STATE=~/botdata/trend-ideas.json LIVE_STATE=~/botdata/live-trend.json
```

Khẩn cấp: `python scripts/exchange.py panic --yes` bán hết coin **bot** đang giữ.

## Đặt lệnh thật cho bot bắt đáy (1h)

`live_dip.py` cho `crypto_bot.py` tự đặt lệnh. Bật cùng biến `LIVE_TRADING` như bot xu hướng.
Vốn ở `CFG["capital"]` (mặc định 120 USDT), chia đều cho 6 suất, tức 20 USDT mỗi lệnh.

Khác bot xu hướng ở chỗ **lệnh bảo vệ nằm sẵn trên sàn** (OCO), vì cắt lỗ 5% / chốt lời 10% /
trailing 7% xảy ra trong giờ, đợi lần chạy sau mới bán là trễ:

| Sổ giấy | Trên sàn |
| --- | --- |
| Mở lệnh trong **giờ này** | Mua market, đặt ngay OCO: chốt lời LIMIT_MAKER + cắt lỗ STOP_LOSS (market) |
| Mở lệnh từ giờ trước | Không mua (vào trễ sau cú xả là vào giá khác) |
| Dời cắt lỗ lên (trailing) ≥ 0,2% | Huỷ OCO cũ, đặt OCO mới |
| Giá chạm mức | Sàn tự khớp ngay, không chờ bot. Lần chạy sau bot ghi lời/lỗ theo giá khớp thật |
| Đóng vì về trung bình 24h / hết hạn giữ | Huỷ OCO, bán market |

Mức trên sàn = mức sổ giấy × (giá khớp thật / giá vào sổ giấy), nên lệnh thật đi đúng % như sổ
giấy. Trên testnet giá lệch hẳn giá thật vẫn chạy đúng.

**Chốt tay = huỷ OCO của lệnh đó trên app, rồi bán.** Coin nằm trong OCO bị khoá nên phải huỷ
trước. Bot thấy OCO bị huỷ không phải do nó thì **nhường hẳn lệnh đó cho bạn**: không đặt lại
OCO, không bán theo luật. Khi bạn bán, nó ghi lời/lỗ. Bot ghi cờ trước mỗi lần tự thay OCO, nên
lỡ chết giữa chừng nó cũng không nhầm thành bạn giành quyền.

```bash
python scripts/live_dip.py test ENA            # testnet: mua + đặt OCO
python scripts/live_dip.py test ENA            # chạy lại: không mua trùng
python scripts/live_dip.py test ENA --trail    # sổ giấy dời cắt lỗ → bot thay OCO
python scripts/live_dip.py test ENA --manual   # giả làm bạn huỷ OCO rồi bán
python scripts/live_dip.py test ENA --rule     # (lệnh khác) sổ giấy đóng → bot huỷ OCO, bán
python scripts/live_dip.py status
python scripts/live_dip.py panic --yes         # huỷ OCO, bán hết lệnh bot giữ (lệnh bạn đã giành thì không đụng)
```

Lệnh `test` dùng sổ riêng (`data/cache/live-dip-test.json`). Sổ thật ở `data/cache/live-dip.json`.
Trên VPS trỏ ra ngoài repo bằng `CRYPTO_STATE` và `LIVE_DIP_STATE`.

## Điều khiển qua Telegram

`tg_control.py` chạy **mỗi phút** trên VPS, đọc lệnh bạn gõ và nút bạn bấm trong chat Telegram:

| Bạn làm | Bot làm |
| --- | --- |
| Bấm **🔴 Đóng lệnh này** dưới tin ĐÃ MUA | Hỏi xác nhận → huỷ OCO (nếu có) → bán market |
| Gõ `/lenh` | Liệt kê lệnh đang mở của cả hai bot: giá vào, giá nay, lời/lỗ, cắt lỗ/chốt lời, mỗi lệnh một nút Đóng |
| Gõ `/dong ENA` | Hỏi xác nhận rồi đóng lệnh ENA (có nhiều lệnh ENA thì cho chọn) |
| Gõ `/dongall` | Hỏi xác nhận rồi đóng tất cả |

Lệnh đóng qua Telegram được ghi lý do *bạn đóng qua Telegram*, và bot **không mua lại** lệnh đó.

An toàn:
- Chỉ nhận lệnh từ đúng `TELEGRAM_CHAT_ID`. Người khác nhắn bot thì bị lờ đi.
- VPS **không mở cổng nào**: máy tự hỏi Telegram (`getUpdates`), không ai gọi vào được.
- Mọi lệnh đóng phải bấm xác nhận lần hai.
- Dùng chung khoá `/tmp/bot.lock` với `run.sh`, nên không bao giờ sửa sổ cùng lúc với bot.
- Lần chạy đầu bỏ qua mọi tin tồn đọng, không làm theo lệnh cũ.

Chậm nhất khoảng 1 phút sau khi bấm thì lệnh được đóng. Nếu đúng lúc bot đang chạy (phút :05), phải chờ bot chạy xong.
Log ở `/home/bot/logs/tg.log`.
