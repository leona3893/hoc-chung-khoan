# Bot phân tích và tín hiệu

Ba script, chạy bằng Python chuẩn (không cần `pip install`):

| Script | Làm gì | Chạy khi nào |
| --- | --- | --- |
| `scan.py` | **Tầng 1** — quét cả sàn (VNALL + HNX30), lọc thanh khoản, chấm điểm nhanh → `data/scan.json` + shortlist | Sau mỗi phiên |
| `fetch_ssi.py` | **Tầng 2** — chấm điểm đầy đủ cho VN30 + mã tay + shortlist → `data/analysis.json`, `data/bars/` | Sau `scan.py` |
| `ideas.py` | **Tầng 3** — mở ý tưởng khi có điểm buy, theo dõi tới điểm sell → `data/ideas.json` | Sau `signals.py` |
| `signals.py` | So bảng điểm phiên mới với phiên trước, tìm những gì vừa đổi → `data/signals.json` + gửi Telegram | Ngay sau `fetch_ssi.py` |
| `backtest.py` | Chạy lại bộ luật trên 5 năm quá khứ → `data/backtest.json` | Khi sửa luật, hoặc hằng tuần |
| `crypto.py` | Khung chiến lược crypto: nhiều chiến lược cắm vào một bộ máy, backtest nến 1h Binance | Khi thêm hoặc sửa chiến lược |
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

## Sửa bộ luật

Toàn bộ điểm nằm trong `analyze()` của `fetch_ssi.py`, bảy thành phần có ghi chú rõ từng mức
điểm. Sau khi sửa:

```bash
python scripts/backtest.py --refresh    # bắt buộc: cache điểm cũ không còn đúng
```

So R trung bình trước và sau. Nếu không cải thiện, đừng giữ thay đổi đó — kể cả khi nó "nghe
hợp lý hơn".
