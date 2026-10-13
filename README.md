# Chứng khoán từ số 0

Tài liệu tự học đầu tư, dạng trang HTML tĩnh — vừa để đọc, vừa là công cụ theo dõi thị trường bằng dữ liệu thật.

## Bốn trang

| Trang | Nội dung |
| --- | --- |
| [`index.html`](index.html) | **Cổ phiếu** — 8 cấp độ từ bản chất cổ phiếu đến hệ thống giao dịch riêng, theo luật chơi HOSE/HNX/UPCoM, kèm 17 hình minh hoạ SVG |
| [`coin.html`](coin.html) | **Coin** — 8 phần về thị trường crypto: khác cổ phiếu ở đâu, sàn và ví, đòn bẩy và funding, chu kỳ, pháp lý ở VN |
| [`chien-luoc.html`](chien-luoc.html) | **Chiến lược** — chiến lược là gì, các trường phái và khung thời gian, năm chiến lược tiêu biểu, các bẫy khi backtest, kèm phòng backtest chạy trên giá thật (VNDirect/Binance) có tính phí, thuế, T+2 và so với mua & giữ, chạy được cả rổ VN30 |
| [`phan-tich.html`](phan-tich.html) | **Phòng phân tích** — quét cả sàn, tín hiệu sau mỗi phiên, sổ theo dõi từ điểm buy tới điểm sell, bảng điểm kỹ thuật, kiểm chứng bộ luật bằng backtest, bảng theo dõi cổ phiếu + coin, đồ thị chỉ báo, nhật ký giao dịch giả lập |

## Dữ liệu

Hai đường, không có backend:

**Tính sẵn sau mỗi phiên** — [`scripts/fetch_ssi.py`](scripts/fetch_ssi.py) tải giá từ API công khai của SSI iBoard, tính chỉ báo, chấm điểm và ghi ra `data/`; rồi [`scripts/signals.py`](scripts/signals.py) so với phiên trước để tìm những gì vừa đổi và gửi Telegram. GitHub Actions chạy cả hai lúc 16:30 giờ Việt Nam các ngày trong tuần ([workflow](.github/workflows/update-data.yml)), và chạy [`scripts/backtest.py`](scripts/backtest.py) chiều thứ Bảy. Chạy tay: `python scripts/fetch_ssi.py` (chỉ dùng thư viện chuẩn, không cần cài gì). Danh sách mã sửa ở [`scripts/watchlist.json`](scripts/watchlist.json). Hướng dẫn chi tiết và cách bật Telegram: [`scripts/README.md`](scripts/README.md).

**Gọi thẳng từ trình duyệt** — cho những gì cần giá ngay:

- **Cổ phiếu VN** — `dchart-api.vndirect.com.vn`, chỉ dùng cho mã chưa có trong `data/`. Mã đã chấm điểm và các chỉ số đọc luôn file local, vừa nhanh vừa khớp số với bảng điểm.
- **Crypto** — API công khai của Binance: nến từ 15 phút đến 1 tuần, giá và biến động 24h, funding rate hợp đồng vĩnh cửu.

Khi không có mạng, phần thực hành ở hai trang bài học lùi về bộ dữ liệu nhúng sẵn (HPG 01/06–07/09/2026 và 120 nến ngày của BTC), nên bài học vẫn đọc và bấm được offline.

## Ba tầng của bot

```
quét sàn (342 mã)  →  lọc thanh khoản → 162 mã có điểm  →  shortlist ~40 mã
                                                              ↓
                           chấm điểm đầy đủ + kế hoạch giá (vùng mua, cắt lỗ, mục tiêu)
                                                              ↓
              tín hiệu "cái gì vừa đổi"  +  sổ theo dõi: điểm buy → theo dõi → điểm sell
                                                              ↓
                     trong phiên: canh ngưỡng giá, nhắn Telegram ngay khi chạm
```

Có thêm một bot crypto chạy song song ([`crypto_bot.py`](scripts/crypto_bot.py)): quét các cặp USDT thanh khoản nhất mỗi khi nến 4h đóng, mở vị thế giấy, theo dõi tới điểm bán. Năm chiến lược cắm rời trong [`crypto.py`](scripts/crypto.py), trong đó hai cái dựng lại từ một kênh tín hiệu công khai — và **cả năm đều âm khi backtest 3 năm**, thua xa mua-giữ BTC (+212%). Số liệu nằm trong [`data/crypto-backtest.json`](data/crypto-backtest.json) và được gắn vào từng tin nhắn của bot.

Bot **không đặt lệnh** và không giữ khoá API giao dịch nào. Lý do dừng ở mức báo tín hiệu nằm ở
mục kiểm chứng: bộ luật này chưa thắng được mua-và-giữ, nên tự động hoá nó chỉ làm mất tiền
nhanh hơn.

## Công cụ trong phòng phân tích

- **Quét sàn** — chấm điểm 342 mã (VNALL + HNX30) sau mỗi phiên, loại mã có giá trị khớp dưới 3 tỷ/phiên, xếp theo điểm. Bảng lọc và sắp xếp được theo mọi cột; mã vào shortlist được chấm lại đầy đủ.
- **Sổ theo dõi ý tưởng** — mã đạt mức MUA được mở thành một ý tưởng, khớp ở giá mở cửa phiên sau, theo dõi từng phiên tới khi chạm cắt lỗ, chạm mục tiêu, bị hạ bậc hoặc hết 40 phiên. Cùng luật với backtest nên thành tích sống so được thẳng với thành tích backtest.
- **Nhắc trước giờ mở cửa** — 8:50 mỗi ngày, đọc lại sổ theo dõi và nhắc đúng việc cần làm: lệnh nào chờ đặt (kèm mức bỏ qua nếu mở cửa nhảy quá xa), mã nào đang giữ và cắt lỗ ở đâu, phiên trước đã đóng lệnh nào.
- **Cảnh báo trong phiên** — mỗi 30 phút từ 9:15 đến 14:45, bot so giá khớp với ngưỡng đã cố định từ phiên trước: mất cắt lỗ, giảm sàn, lùi vào vùng mua, chạm mục tiêu. Không chấm điểm lại giữa phiên (nến chưa đóng), chỉ gửi Telegram, không commit gì vào repo.
- **Tín hiệu phiên này** — bot quét sau mỗi phiên và chỉ liệt kê cái vừa *thay đổi*: mã đổi bậc khuyến nghị, lùi về vùng mua, mất điểm cắt lỗ hoặc đạt mục tiêu của kế hoạch phiên trước, setup kỹ thuật mới xuất hiện, thị trường đổi trạng thái. Chia ba mức ưu tiên, gửi được qua Telegram. **Bot không đặt lệnh và không giữ khoá API giao dịch nào.**
- **Kiểm chứng bộ luật** — backtest point-in-time 5 năm, có phí, thuế, trượt giá, T+2 và lô 100; so 11 cách vào/thoát lệnh với mua-và-giữ VN-Index, trên cả rổ VN30 và rổ quét sàn 159 mã. Kết quả: **chưa biến thể nào thắng mua-và-giữ về lợi nhuận** (tốt nhất +14,8% so với +27,7% trong 5 năm) nhưng sụt vốn nhẹ hơn hẳn (−23,0% so với −40,3%). Phát hiện đáng giá nhất: trên rổ rộng, **bỏ chốt lời cứng** đưa R trung bình từ −0,08 lên **+0,54/lệnh** — chỗ rò rỉ nằm ở mục tiêu đặt quá gần, không nằm ở cách chọn mã. Con số nằm ngay trên trang, không bị giấu.
- **Bảng điểm & khuyến nghị** — chấm 34 mã (VN30 + vài mã thêm) trên thang ±100 theo bảy thành phần: cấu trúc xu hướng, động lượng, khối lượng, sức mạnh tương đối so với VN-Index, khối ngoại, vị trí 52 tuần và phanh rủi ro ngắn hạn. Quy ra năm mức từ MUA đến BÁN, kèm **toàn bộ lý do cho từng điểm cộng trừ**, vùng hỗ trợ/kháng cự, điểm cắt lỗ, mục tiêu và tỷ lệ lời/lỗ. Lọc, tìm và sắp xếp được theo mọi cột.
- **Bối cảnh thị trường** — VN-Index, VN30, HNX-Index kèm độ rộng (bao nhiêu mã trên MA20/50/200). Nếu VN-Index dưới MA50 thì mọi khuyến nghị bị chặn tối đa ở mức TÍCH LŨY.
- **Bảng theo dõi** — thêm mã cổ phiếu hoặc coin, xem giá, thay đổi, cao/thấp, khối lượng và đường giá 30 nến. Danh sách nhớ trong trình duyệt.
- **Đồ thị** — nến + khối lượng, MA20/50/200, Bollinger, RSI 14. Bấm vào một cây nến để trang tự đọc nó: tỷ lệ thân–bóng, khối lượng so với trung bình 20 nến, vị trí so với từng chỉ báo đang bật.
- **Nhật ký giao dịch giả lập** — ghi lệnh trên giấy với giá vào, cắt lỗ, chốt lời và lý do. Tự tính tỷ lệ lãi/lỗ, rủi ro theo tiền, số R, tỷ lệ thắng và R trung bình. Lệnh đang mở cập nhật lãi/lỗ theo giá thật. Lưu trong `localStorage`, xuất được ra JSON.

## Cấu trúc

```
index.html      bài học cổ phiếu
coin.html       bài học coin
chien-luoc.html bài học chiến lược + phòng backtest
phan-tich.html  phòng phân tích
assets/
  site.css      toàn bộ giao diện
  site.js       tiến độ học, scrollspy, hiệu ứng hình
  chart.js      engine đồ thị nến + chỉ báo, dùng chung cả ba trang
  market.js     lớp gọi API VNDirect và Binance
  journal.js    nhật ký giao dịch giả lập
  btc-fallback.json  dữ liệu BTC dự phòng khi mất mạng
scripts/
  fetch_ssi.py    tải dữ liệu SSI, tính chỉ báo, chấm điểm
  scan.py         quét cả sàn, lọc thanh khoản, chọn shortlist
  signals.py      so hai phiên, phát tín hiệu, gửi Telegram
  ideas.py        sổ theo dõi: điểm buy → theo dõi → điểm sell
  morning.py      nhắc việc cần làm trước giờ mở cửa
  intraday.py     canh ngưỡng giá trong phiên, gửi Telegram
  telegram_setup.py  lấy chat id, gửi thử một tin
  crypto.py       khung chiến lược crypto + backtest nến Binance/OKX
  crypto_bot.py   bot tín hiệu crypto: quét, ra điểm mua, theo dõi, ra điểm bán
  backtest.py     chạy lại bộ luật trên 5 năm quá khứ
  watchlist.json  danh sách mã được chấm điểm
  README.md       cách chạy bot, bật Telegram, đọc backtest
data/
  scan.json       kết quả quét sàn, bảng gọn mọi mã qua lọc
  ideas.json      sổ theo dõi ý tưởng đang mở và đã đóng
  analysis.json   bối cảnh thị trường + bảng điểm rổ chính
  signals.json    tín hiệu phiên mới nhất + lịch sử 45 ngày
  backtest.json   kết quả kiểm chứng bộ luật
  crypto-backtest.json  kết quả 5 chiến lược crypto trên 3 năm nến
  crypto-ideas.json     sổ vị thế giấy của bot crypto
  bars/<mã>.json  nến và chỉ báo từng mã, tải khi cần
```

## Cách xem

Xem trực tiếp: **https://leona3893.github.io/hoc-chung-khoan/**

Hoặc chạy ở máy — cần một web server nhỏ vì các trang nạp file từ `assets/`, mở thẳng bằng `file://` sẽ bị chặn:

```bash
git clone https://github.com/leona3893/hoc-chung-khoan.git
cd hoc-chung-khoan
python -m http.server 8000
# mở http://localhost:8000
```

> Điểm số, tín hiệu và khuyến nghị là kết quả tính toán tự động theo luật cố định, phục vụ học tập — không phải khuyến nghị đầu tư, tư vấn pháp lý hay thuế. Dữ liệu lấy từ API công khai của bên thứ ba, có thể trễ hoặc gián đoạn. Nhật ký giao dịch là sổ ghi chép cá nhân trên máy bạn — không có lệnh nào được gửi tới sàn nào.
