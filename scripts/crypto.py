#!/usr/bin/env python3
"""
Khung chiến lược crypto: một bộ máy, nhiều chiến lược cắm vào.

Tách đúng ba phần, như bot tín hiệu nào cũng nên làm:

    [ ĐIỀU KIỆN VÀO ]   mỗi chiến lược là một hàm ~15 dòng, thêm bớt tự do
    [ KHỐI THOÁT LỆNH ] cắt lỗ / chốt lời / trailing / giữ tối đa — dùng chung
    [ MÔ PHỎNG + BÁO ]  phí, trượt giá, trần vị thế, thống kê R — dùng chung

Chạy backtest mọi chiến lược trên mọi cặp rồi so với mua-và-giữ BTC, tách riêng
giai đoạn BTC trên và dưới MA200 (một chiến lược bắt đáy sống được trong sóng tăng
mà chết trong sóng giảm thì phải thấy được điều đó, không thì con số trung bình nói dối).

    python scripts/crypto.py                      # backtest đủ, dùng cache
    python scripts/crypto.py --pairs 20           # chỉ 20 cặp thanh khoản nhất
    python scripts/crypto.py --refresh            # tải lại nến
    python scripts/crypto.py --strategy vcr       # chạy một chiến lược
    python scripts/crypto.py --list               # xem danh sách chiến lược

Đầu ra: data/crypto-backtest.json
Chỉ dùng thư viện chuẩn. Không cần API key — nến là dữ liệu công khai.
"""

import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
CACHE_DIR = os.path.join(DATA_DIR, "cache", "crypto")
OUT_PATH = os.path.join(DATA_DIR, "crypto-backtest.json")

VN_TZ = timezone(timedelta(hours=7))
HOSTS = ["https://api.binance.com", "https://data-api.binance.vision"]
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"}

# Stablecoin và token đòn bẩy — bỏ, vì nến của chúng không phải giá tài sản thật
STABLE = {"USDC", "FDUSD", "TUSD", "USD1", "RLUSD", "BUSD", "DAI", "USDP", "USDE",
          "EUR", "TRY", "BRL", "ARS", "XUSD", "AEUR"}

# Cả hai sàn đều niêm yết hàng trăm cổ phiếu và ETF Mỹ token hoá. Chúng KHÔNG phải
# coin: giá bám cổ phiếu cơ sở, nên chiến lược crypto áp lên đó là so sai thị trường.
# Hai sàn đặt tên khác nhau:
#   Binance: mã chứng khoán + "B"   → AAPLB, TSLAB, NVDAB, SPYB, SNDKB
#   OKX:     "X" + mã chứng khoán   → XAAPL, XTSLA, XNVDA, XSPY, XSNDK
# Không sàn nào đánh dấu chúng trong metadata, nên chỉ còn cách lọc theo tên. Nhầm một
# token cổ phiếu tốn kém hơn nhiều so với bỏ sót một coin, nên lọc theo hướng thận
# trọng: loại hết, trừ các coin thật trong hai danh sách dưới. Gặp mã mới thì thêm vào.
NOT_STOCK_B = {"SHIB", "BNB", "COMB", "CLUB", "JOB"}
NOT_STOCK_X = {"XRP", "XLM", "XMR", "XTZ", "XCH", "XEC", "XDC", "XVG", "XNO",
               "XAUT", "XCN", "XYO", "XAI", "XPL", "XDB", "XMT"}


def is_stock_token(base):
    if base.endswith("B") and len(base) >= 4 and base not in NOT_STOCK_B:
        return True
    if base.startswith("X") and len(base) >= 3 and base not in NOT_STOCK_X:
        return True
    return False

# ---------------------------------------------------------------------------
# Khối thoát lệnh dùng chung — đúng bộ tham số bot kia in trên chart
# ---------------------------------------------------------------------------
EXIT = {
    "slPct": 5.0,       # cắt lỗ 5% dưới giá vào
    "tpPct": 10.0,      # chốt lời 10%
    "trailPct": 7.0,    # dời cắt lỗ theo 7% dưới đỉnh cao nhất kể từ khi vào
    "maxHold": 72,      # giữ tối đa 72 nến 1h = 3 ngày
}
COST = {
    "fee": 0.001,       # 0,1% mỗi chiều (taker Binance)
    "slip": 0.0005,     # trượt giá 0,05% mỗi chiều
}
PORT = {
    "capital": 10000.0,   # vốn 10.000 USDT
    "riskPct": 1.0,       # rủi ro 1% vốn mỗi lệnh → cỡ vị thế = 1%/slPct
    "maxOpen": 5,         # tối đa 5 vị thế mở cùng lúc, mỗi cặp một lệnh
}


# ---------------------------------------------------------------------------
# Chỉ báo
# ---------------------------------------------------------------------------
def sma(xs, n):
    out, s = [None] * len(xs), 0.0
    for i, x in enumerate(xs):
        s += x
        if i >= n:
            s -= xs[i - n]
        out[i] = s / n if i >= n - 1 else None
    return out


def rsi(xs, n=14):
    out = [None] * len(xs)
    g = l = 0.0
    for i in range(1, len(xs)):
        ch = xs[i] - xs[i - 1]
        gain, loss = max(ch, 0.0), max(-ch, 0.0)
        if i <= n:
            g += gain
            l += loss
            if i < n:
                continue
            g /= n
            l /= n
        else:
            g = (g * (n - 1) + gain) / n
            l = (l * (n - 1) + loss) / n
        out[i] = 100.0 if l == 0 else 100 - 100 / (1 + g / l)
    return out


def stdev(xs, n):
    out = [None] * len(xs)
    for i in range(n - 1, len(xs)):
        seg = xs[i - n + 1:i + 1]
        m = sum(seg) / n
        out[i] = math.sqrt(sum((x - m) ** 2 for x in seg) / n)
    return out


class Ctx:
    """Mọi chỉ báo tính sẵn một lần cho mỗi cặp, chiến lược chỉ việc đọc."""

    def __init__(self, bars):
        self.t = [b[0] for b in bars]
        self.o = [b[1] for b in bars]
        self.h = [b[2] for b in bars]
        self.l = [b[3] for b in bars]
        self.c = [b[4] for b in bars]
        self.v = [b[5] for b in bars]
        self.sma14 = sma(self.c, 14)
        self.sma20 = sma(self.c, 20)
        self.sma50 = sma(self.c, 50)
        self.sma100 = sma(self.c, 100)
        self.sma200 = sma(self.c, 200)
        self.rsi14 = rsi(self.c, 14)
        self.vavg20 = sma(self.v, 20)
        sd = stdev(self.c, 20)
        self.bbUp = [None if (self.sma20[i] is None or sd[i] is None) else self.sma20[i] + 2 * sd[i]
                     for i in range(len(bars))]
        self.bbLo = [None if (self.sma20[i] is None or sd[i] is None) else self.sma20[i] - 2 * sd[i]
                     for i in range(len(bars))]
        self.bbW = [None if (self.bbUp[i] is None or not self.sma20[i]) else
                    (self.bbUp[i] - self.bbLo[i]) / self.sma20[i] * 100 for i in range(len(bars))]

    def drop(self, i, k=1):
        """Mức giảm (%) của nến i so với đóng cửa k nến trước."""
        if i - k < 0 or not self.c[i - k]:
            return 0.0
        return (self.c[i] / self.c[i - k] - 1) * 100

    def volx(self, i):
        a = self.vavg20[i]
        return (self.v[i] / a) if a else 0.0


# ---------------------------------------------------------------------------
# Các chiến lược — mỗi cái chỉ trả lời: nến i đã đóng, có vào lệnh không?
# ---------------------------------------------------------------------------
def s_vcr(x, i, p):
    """Volume climax reversal: xả mạnh kèm khối lượng đột biến, giá dưới SMA14.
    Dựng lại từ chiến lược 'vcr' của một bot tín hiệu công khai."""
    return (x.drop(i) <= -p["drop"]
            and x.volx(i) >= p["volx"]
            and x.sma14[i] is not None and x.c[i] < x.sma14[i])


def s_rsi_vol(x, i, p):
    """RSI quá bán, có khối lượng xác nhận. Dựng lại từ 'rsi_vol_gated'."""
    return (x.rsi14[i] is not None and x.rsi14[i] <= p["rsi"]
            and x.volx(i) >= p["volx"])


def s_ma_cross(x, i, p):
    """MA20 cắt lên MA50 — theo xu hướng, để làm đối chứng với hai cái bắt đáy."""
    if i < 1 or None in (x.sma20[i], x.sma50[i], x.sma20[i - 1], x.sma50[i - 1]):
        return False
    return x.sma20[i - 1] <= x.sma50[i - 1] and x.sma20[i] > x.sma50[i]


def s_breakout(x, i, p):
    """Phá đỉnh N nến kèm khối lượng."""
    if i < p["look"] + 1 or x.vavg20[i] is None:
        return False
    prior = max(x.h[i - p["look"]:i])
    return x.c[i] > prior and x.volx(i) >= p["volx"]


def s_bb_bounce(x, i, p):
    """Đóng cửa dưới dải Bollinger dưới rồi bật lên — bắt đáy theo biến động."""
    if i < 1 or None in (x.bbLo[i], x.bbLo[i - 1]):
        return False
    return x.c[i - 1] < x.bbLo[i - 1] and x.c[i] > x.c[i - 1]


# --- Nhóm theo xu hướng: vào khi giá đã lên, ra khi xu hướng gãy.
#     Ngược hẳn nhóm bắt đáy ở trên, và thoát bằng luật chứ không chốt lời cứng.
def s_above_ma200(x, i, p):
    """Giá vượt lên trên MA200 — bộ lọc xu hướng kinh điển nhất."""
    if i < 1 or None in (x.sma200[i], x.sma200[i - 1]):
        return False
    return x.c[i - 1] <= x.sma200[i - 1] and x.c[i] > x.sma200[i]


def e_below_ma200(x, i, p):
    return x.sma200[i] is not None and x.c[i] < x.sma200[i]


def s_golden(x, i, p):
    """MA50 cắt lên MA200."""
    if i < 1 or None in (x.sma50[i], x.sma200[i], x.sma50[i - 1], x.sma200[i - 1]):
        return False
    return x.sma50[i - 1] <= x.sma200[i - 1] and x.sma50[i] > x.sma200[i]


def e_death(x, i, p):
    if None in (x.sma50[i], x.sma200[i]):
        return False
    return x.sma50[i] < x.sma200[i]


def s_donchian(x, i, p):
    """Phá đỉnh N nến — luật của nhóm Turtle."""
    n = p.get("inn", 20)
    if i < n + 1:
        return False
    return x.c[i] > max(x.h[i - n:i])


def e_donchian(x, i, p):
    n = p.get("out", 10)
    if i < n + 1:
        return False
    return x.c[i] < min(x.l[i - n:i])


def s_ma100(x, i, p):
    if i < 1 or None in (x.sma100[i], x.sma100[i - 1]):
        return False
    return x.c[i - 1] <= x.sma100[i - 1] and x.c[i] > x.sma100[i]


def e_ma100(x, i, p):
    return x.sma100[i] is not None and x.c[i] < x.sma100[i]


STRATEGIES = {
    "ma200": {"fn": s_above_ma200, "exitFn": e_below_ma200, "params": {},
              "label": "Vượt lên MA200, ra khi mất MA200 (theo xu hướng)"},
    "ma100": {"fn": s_ma100, "exitFn": e_ma100, "params": {},
              "label": "Vượt lên MA100, ra khi mất MA100 (theo xu hướng)"},
    "golden": {"fn": s_golden, "exitFn": e_death, "params": {},
               "label": "MA50 cắt lên MA200, ra khi cắt xuống (theo xu hướng)"},
    "donchian": {"fn": s_donchian, "exitFn": e_donchian, "params": {"inn": 20, "out": 10},
                 "label": "Phá đỉnh 20 nến, ra khi thủng đáy 10 nến (Turtle)"},
    "vcr": {"fn": s_vcr, "params": {"drop": 3.0, "volx": 2.5},
            "label": "Xả mạnh + khối lượng đột biến (bắt đáy)"},
    "rsi_vol_gated": {"fn": s_rsi_vol, "params": {"rsi": 25.0, "volx": 2.0},
                      "label": "RSI quá bán + khối lượng xác nhận (bắt đáy)"},
    "ma_cross": {"fn": s_ma_cross, "params": {},
                 "label": "MA20 cắt lên MA50 (theo xu hướng)"},
    "breakout": {"fn": s_breakout, "params": {"look": 24, "volx": 1.5},
                 "label": "Phá đỉnh 24 nến kèm khối lượng (theo xu hướng)"},
    "bb_bounce": {"fn": s_bb_bounce, "params": {},
                  "label": "Bật lên từ dưới dải Bollinger (bắt đáy)"},
}


# ---------------------------------------------------------------------------
# Dữ liệu
# ---------------------------------------------------------------------------
class GeoBlocked(RuntimeError):
    """Binance trả 451 — vùng này bị chặn, phải dùng nguồn khác."""


def get(url, retries=3):
    last = None
    for k in range(retries):
        for host in HOSTS:
            try:
                req = urllib.request.Request(host + url, headers=HEADERS)
                with urllib.request.urlopen(req, timeout=30) as r:
                    return json.load(r)
            except urllib.error.HTTPError as e:
                last = e
                if e.code == 451:
                    # Binance chặn một số vùng, trong đó có dải IP của GitHub Actions.
                    # Không retry vô ích — để bên gọi chuyển sang nguồn dự phòng.
                    raise GeoBlocked(f"Binance chặn vùng này (451)")
            except Exception as e:  # noqa: BLE001
                last = e
        time.sleep(1.5 * (k + 1))
    raise RuntimeError(f"Không lấy được {url}: {last}")


# ---------------------------------------------------------------------------
# Nguồn dự phòng: OKX. Cùng dữ liệu nến, khác định dạng và thứ tự.
# ---------------------------------------------------------------------------
OKX_BAR = {"1h": "1H", "2h": "2H", "4h": "4H", "6h": "6H", "12h": "12H", "1d": "1D"}


def okx_klines(symbol, interval, limit=300, before=None):
    """Trả về [[ts, o, h, l, c, v], ...] sắp theo thời gian tăng dần."""
    q = {"instId": (symbol[:-4] + "-USDT") if symbol.endswith("USDT") else symbol,
         "bar": OKX_BAR.get(interval, "1H"), "limit": min(limit, 300)}
    if before:
        q["after"] = before     # OKX: 'after' nghĩa là lấy các nến CŨ HƠN mốc này
    req = urllib.request.Request("https://www.okx.com/api/v5/market/candles?"
                                 + urllib.parse.urlencode(q), headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.load(r)
    rows = d.get("data") or []
    out = [[int(x[0]), float(x[1]), float(x[2]), float(x[3]), float(x[4]), float(x[5])]
           for x in rows]
    out.sort(key=lambda b: b[0])
    return out


def okx_liquid_pairs(limit, min_vol=1e7):
    req = urllib.request.Request("https://www.okx.com/api/v5/market/tickers?instType=SPOT",
                                 headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.load(r)
    rows = []
    for x in d.get("data") or []:
        inst = x.get("instId", "")
        if not inst.endswith("-USDT"):
            continue
        base = inst[:-5]
        if base in STABLE or is_stock_token(base):
            continue
        try:
            qv = float(x.get("volCcy24h") or 0) * float(x.get("last") or 0)
        except (TypeError, ValueError):
            continue
        if qv >= min_vol:
            rows.append((qv, base + "USDT"))
    rows.sort(reverse=True)
    return [s for _, s in rows[:limit]]


def okx_history(symbol, interval, start):
    """Lấy ngược về quá khứ từng trang 300 nến cho tới khi phủ hết khoảng cần."""
    out, before = [], None
    for _ in range(80):
        page = okx_klines(symbol, interval, 300, before)
        if not page:
            break
        out = page + out
        before = str(page[0][0])
        if page[0][0] <= start:
            break
        time.sleep(0.12)
    return [b for b in out if b[0] >= start]


UNIVERSE_PATH = os.path.join(DATA_DIR, "crypto-universe.json")


def universe(limit, min_vol=1e7):
    """Rổ cặp để quét — LUÔN là coin của Binance, không bao giờ lấy từ nơi khác.

    Binance chặn IP của GitHub Actions, mà danh sách cặp của OKX có hàng trăm cổ
    phiếu Mỹ token hoá đặt tên khác hẳn. Nên khi bị chặn, ta dùng lại bản chụp rổ
    Binance đã lưu trong repo thay vì hỏi sàn khác. Nến thì vẫn lấy từ OKX được,
    vì lúc đó ta đã biết chính xác mình cần mã nào.
    """
    try:
        pairs = liquid_pairs(limit, min_vol)
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(UNIVERSE_PATH, "w", encoding="utf-8") as f:
            json.dump({"updatedAt": datetime.now(VN_TZ).strftime("%Y-%m-%d %H:%M"),
                       "source": "binance", "minVol": min_vol, "pairs": pairs},
                      f, ensure_ascii=False, indent=1)
        return pairs
    except GeoBlocked:
        if os.path.exists(UNIVERSE_PATH):
            with open(UNIVERSE_PATH, encoding="utf-8") as f:
                d = json.load(f)
            pairs = [p for p in d.get("pairs", []) if not is_stock_token(p[:-4])][:limit]
            print(f"[nguồn] Binance chặn vùng này — dùng rổ đã lưu "
                  f"({len(pairs)} cặp, cập nhật {d.get('updatedAt')}).", file=sys.stderr)
            return pairs
        raise RuntimeError("Binance chặn vùng này và chưa có data/crypto-universe.json. "
                           "Chạy script này một lần ở nơi gọi được Binance để tạo rổ.")


def liquid_pairs(limit, min_vol=1e7):
    tickers = get("/api/v3/ticker/24hr")
    rows = []
    for x in tickers:
        s = x["symbol"]
        if not s.endswith("USDT"):
            continue
        base = s[:-4]
        if base in STABLE or is_stock_token(base) or base.endswith("UP") or base.endswith("DOWN"):
            continue
        qv = float(x["quoteVolume"])
        if qv >= min_vol:
            rows.append((qv, s))
    rows.sort(reverse=True)
    return [s for _, s in rows[:limit]]


def klines(symbol, interval, months, refresh=False):
    """Nến 1h, cache theo ngày để chạy lại cho nhanh."""
    p = os.path.join(CACHE_DIR, f"{symbol}-{interval}.json")
    today = datetime.now(VN_TZ).strftime("%Y-%m-%d")
    end = int(time.time() * 1000)
    start = end - int(months * 30.44 * 86400 * 1000)
    if not refresh and os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            # Chỉ dùng lại cache khi nó phủ ĐỦ khoảng đang hỏi. Thiếu kiểm tra này thì
            # một lần chạy thử ngắn sẽ âm thầm làm hỏng mọi lần chạy dài sau đó.
            bars = d.get("bars") or []
            if d.get("day") == today and bars and bars[0][0] <= start + 2 * 3600 * 1000:
                return bars
        except Exception:  # noqa: BLE001
            pass

    src = "binance"
    bars, cur = [], start
    try:
        while cur < end:
            q = urllib.parse.urlencode({"symbol": symbol, "interval": interval,
                                        "startTime": cur, "limit": 1000})
            rows = get("/api/v3/klines?" + q)
            if not rows:
                break
            for r in rows:
                bars.append([int(r[0]), float(r[1]), float(r[2]), float(r[3]),
                             float(r[4]), float(r[5])])
            nxt = rows[-1][0] + 1
            if nxt <= cur:
                break
            cur = nxt
            if len(rows) < 1000:
                break
    except GeoBlocked:
        print("[nguồn] Binance chặn vùng này — lấy nến từ OKX.", file=sys.stderr)
        bars, src = okx_history(symbol, interval, start), "okx"

    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"symbol": symbol, "interval": interval, "day": today,
                   "months": months, "source": src, "bars": bars},
                  f, separators=(",", ":"))
    return bars


# ---------------------------------------------------------------------------
# Mô phỏng
# ---------------------------------------------------------------------------
def simulate(name, strat, ctxs, calendar, regime, exits):
    """Chạy một chiến lược trên toàn bộ cặp. Tín hiệu ở nến đóng i → vào ở mở cửa nến i+1."""
    fn, params = strat["fn"], strat["params"]
    equity = PORT["capital"]
    cash = equity
    open_pos = {}          # symbol -> vị thế
    trades = []
    curve = []
    idx = {s: {t: i for i, t in enumerate(c.t)} for s, c in ctxs.items()}

    for k, ts in enumerate(calendar):
        # --- thoát
        for sym in list(open_pos):
            x = ctxs[sym]
            i = idx[sym].get(ts)
            if i is None:
                continue
            p = open_pos[sym]
            p["held"] += 1
            p["peak"] = max(p["peak"], x.h[i])
            if exits.get("trailPct"):
                t_stop = p["peak"] * (1 - exits["trailPct"] / 100)
                if t_stop > p["stop"]:
                    p["stop"] = t_stop
                    p["trailed"] = True
            px = reason = None
            exit_fn = strat.get("exitFn")
            if p["stop"] and x.l[i] <= p["stop"]:
                px = min(x.o[i], p["stop"])
                reason = "trail" if p["trailed"] else "stop"
            elif exits.get("tpPct") and p.get("tp") and x.h[i] >= p["tp"]:
                px = max(x.o[i], p["tp"])
                reason = "tp"
            elif exit_fn and exit_fn(x, i, params):
                # Chiến lược theo xu hướng tự quyết lúc nào ra, không chốt lời cứng
                px = x.c[i]
                reason = "rule"
            elif exits.get("maxHold") and p["held"] >= exits["maxHold"]:
                px = x.c[i]
                reason = "max_hold"
            if px is None:
                continue
            fill = px * (1 - COST["slip"])
            proceeds = fill * p["qty"] * (1 - COST["fee"])
            cash += proceeds
            pnl = proceeds - p["cost"]
            risk = (p["fill"] - p["stop0"]) * p["qty"]
            trades.append({
                "symbol": sym, "entryTs": p["ts"], "exitTs": ts,
                "entry": p["fill"], "exit": fill, "held": p["held"], "reason": reason,
                "pnl": pnl, "pnlPct": (fill / p["fill"] - 1) * 100,
                "r": pnl / risk if risk > 0 else None,
                "regime": p["regime"],
            })
            del open_pos[sym]

        # --- vào: tín hiệu của nến trước, khớp ở mở cửa nến này
        if k > 0 and len(open_pos) < PORT["maxOpen"]:
            prev = calendar[k - 1]
            cands = []
            for sym, x in ctxs.items():
                if sym in open_pos:
                    continue
                i = idx[sym].get(prev)
                j = idx[sym].get(ts)
                if i is None or j is None or i < 60:
                    continue
                try:
                    if fn(x, i, params):
                        cands.append((x.volx(i), sym, j))
                except Exception:  # noqa: BLE001
                    continue
            cands.sort(reverse=True)
            for _, sym, j in cands:
                if len(open_pos) >= PORT["maxOpen"]:
                    break
                x = ctxs[sym]
                fill = x.o[j] * (1 + COST["slip"])
                stop = fill * (1 - exits["slPct"] / 100) if exits.get("slPct") else None
                risk_money = equity * PORT["riskPct"] / 100
                # Không có cắt lỗ cứng (chiến lược theo xu hướng) thì chia đều vốn
                qty = (risk_money / (fill - stop) if stop
                       else (equity / PORT["maxOpen"]) / fill)
                cost = fill * qty * (1 + COST["fee"])
                if cost > cash:
                    qty = cash / (fill * (1 + COST["fee"]))
                    cost = cash
                if qty <= 0 or cost <= 0:
                    continue
                cash -= cost
                open_pos[sym] = {
                    "qty": qty, "fill": fill, "cost": cost, "ts": ts, "held": 0,
                    "stop": stop, "stop0": stop or fill * 0.9, "trailed": False, "peak": x.h[j],
                    "tp": fill * (1 + exits["tpPct"] / 100) if exits.get("tpPct") else None,
                    "regime": regime.get(ts, "?"),
                }

        # --- định giá
        mtm = cash
        for sym, p in open_pos.items():
            i = idx[sym].get(ts)
            mtm += (ctxs[sym].c[i] if i is not None else p["fill"]) * p["qty"]
        equity = mtm
        if k % 24 == 0:
            curve.append([ts, round(mtm, 2)])

    return stats(name, strat["label"], trades, curve)


def max_dd(curve):
    peak, worst = curve[0][1], 0.0
    for _, v in curve:
        peak = max(peak, v)
        worst = min(worst, (v / peak - 1) * 100)
    return worst


def stats(name, label, trades, curve):
    start_v, end_v = curve[0][1], curve[-1][1]
    days = (curve[-1][0] - curve[0][0]) / 86400000 or 1
    years = days / 365.25
    rs = [t["r"] for t in trades if t["r"] is not None]
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    gw = sum(t["pnl"] for t in wins)
    gl = -sum(t["pnl"] for t in losses)
    by_reason, by_regime = {}, {}
    for t in trades:
        by_reason[t["reason"]] = by_reason.get(t["reason"], 0) + 1
        g = by_regime.setdefault(t["regime"], {"trades": 0, "r": 0.0, "wins": 0})
        g["trades"] += 1
        g["wins"] += 1 if t["pnl"] > 0 else 0
        if t["r"] is not None:
            g["r"] += t["r"]
    for g in by_regime.values():
        g["avgR"] = round(g["r"] / g["trades"], 3) if g["trades"] else None
        g["r"] = round(g["r"], 2)
        g["winRatePct"] = round(g["wins"] / g["trades"] * 100, 1) if g["trades"] else None
    return {
        "name": name, "label": label,
        "trades": len(trades),
        "winRatePct": round(len(wins) / len(trades) * 100, 1) if trades else None,
        "avgR": round(sum(rs) / len(rs), 3) if rs else None,
        "totalR": round(sum(rs), 1) if rs else None,
        "avgWinR": round(sum(t["r"] for t in wins if t["r"] is not None) / len(wins), 2) if wins else None,
        "avgLossR": round(sum(t["r"] for t in losses if t["r"] is not None) / len(losses), 2) if losses else None,
        "profitFactor": round(gw / gl, 2) if gl > 0 else None,
        "totalRetPct": round((end_v / start_v - 1) * 100, 2),
        "cagrPct": round(((end_v / start_v) ** (1 / years) - 1) * 100, 2) if years > 0.1 else None,
        "maxDdPct": round(max_dd(curve), 2),
        "avgHoldH": round(sum(t["held"] for t in trades) / len(trades), 1) if trades else None,
        "byReason": by_reason,
        "byRegime": by_regime,
        "curve": [{"t": t, "v": v} for t, v in curve[::max(1, len(curve) // 300)]],
        "tradeList": trades[-60:],
    }


def buy_hold(ctx, calendar):
    idx = {t: i for i, t in enumerate(ctx.t)}
    curve, base = [], None
    for k, ts in enumerate(calendar):
        i = idx.get(ts)
        if i is None:
            continue
        if base is None:
            base = ctx.c[i]
        if k % 24 == 0:
            curve.append([ts, round(PORT["capital"] * ctx.c[i] / base, 2)])
    if len(curve) < 2:
        return None
    return stats("benchmark", "Mua và giữ BTC", [], curve)


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", type=int, default=30, help="số cặp thanh khoản nhất")
    ap.add_argument("--months", type=float, default=24, help="số tháng lịch sử")
    ap.add_argument("--strategy", help="chỉ chạy một chiến lược")
    ap.add_argument("--interval", default="1h", help="khung nến: 1h, 4h, 1d")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    if args.list:
        for k, v in STRATEGIES.items():
            print(f"  {k:<16} {v['label']}  {v['params']}")
        return 0

    # maxHold đếm bằng số nến: quy đổi để mọi khung giữ cùng số giờ
    per = {"1h": 1, "2h": 2, "4h": 4, "6h": 6, "12h": 12, "1d": 24}.get(args.interval, 1)
    if per > 1:
        EXIT["maxHold"] = max(3, EXIT["maxHold"] // per)
        print(f"Khung {args.interval}: giữ tối đa {EXIT['maxHold']} nến "
              f"(= {EXIT['maxHold'] * per} giờ)", file=sys.stderr)

    t0 = time.time()
    pairs = liquid_pairs(args.pairs)
    if "BTCUSDT" not in pairs:
        pairs.append("BTCUSDT")
    print(f"{len(pairs)} cặp, {args.months:.0f} tháng nến {args.interval}.", file=sys.stderr)

    ctxs = {}
    for n, sym in enumerate(pairs, 1):
        try:
            bars = klines(sym, args.interval, args.months, args.refresh)
            if len(bars) < 500:
                print(f"  [bỏ] {sym}: {len(bars)} nến", file=sys.stderr)
                continue
            ctxs[sym] = Ctx(bars)
            if n % 10 == 0:
                print(f"  …{n}/{len(pairs)} ({time.time()-t0:.0f}s)", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print(f"  [lỗi] {sym}: {e}", file=sys.stderr)
    if "BTCUSDT" not in ctxs:
        print("Thiếu BTCUSDT để làm chuẩn so sánh.", file=sys.stderr)
        return 1

    btc = ctxs["BTCUSDT"]
    ma200d = sma(btc.c, max(2, 200 * 24 // per))   # MA200 ngày, quy ra số nến của khung
    regime = {btc.t[i]: ("tăng" if (ma200d[i] and btc.c[i] > ma200d[i]) else "giảm")
              for i in range(len(btc.t))}
    calendar = sorted({t for c in ctxs.values() for t in c.t})
    print(f"Lịch: {len(calendar)} nến, "
          f"{datetime.fromtimestamp(calendar[0]/1000, VN_TZ):%d/%m/%Y} → "
          f"{datetime.fromtimestamp(calendar[-1]/1000, VN_TZ):%d/%m/%Y}", file=sys.stderr)

    names = [args.strategy] if args.strategy else list(STRATEGIES)
    variants = [
        ("gốc", dict(EXIT)),
        ("không chốt lời", {**EXIT, "tpPct": None}),
        ("không chốt lời, trail 10%", {**EXIT, "tpPct": None, "trailPct": 10.0}),
        ("giữ tối đa 240h", {**EXIT, "tpPct": None, "maxHold": max(3, 240 // per)}),
    ]

    results = []
    for nm in names:
        strat = STRATEGIES[nm]
        for vname, ex in variants:
            r = simulate(nm, strat, ctxs, calendar, regime, ex)
            r["variant"] = vname
            r["exits"] = {k: v for k, v in ex.items()}
            results.append(r)
            print(f"  {nm:<16} {vname:<26} {r['trades']:>5} lệnh  "
                  f"thắng {r['winRatePct'] or 0:>5.1f}%  R tb {r['avgR'] if r['avgR'] is not None else 0:>6.3f}  "
                  f"lãi {r['totalRetPct']:>8.2f}%  DD {r['maxDdPct']:>7.2f}%", file=sys.stderr)

    bh = buy_hold(btc, calendar)
    if bh:
        bh["variant"] = "—"
        results.append(bh)
        print(f"  {'benchmark':<16} {'mua và giữ BTC':<26} {'':>5}            "
              f"           lãi {bh['totalRetPct']:>8.2f}%  DD {bh['maxDdPct']:>7.2f}%", file=sys.stderr)

    out = {
        "updatedAt": datetime.now(VN_TZ).strftime("%Y-%m-%d %H:%M"),
        "source": f"Binance public klines {args.interval}",
        "interval": args.interval,
        "pairs": sorted(ctxs),
        "period": {"from": calendar[0], "to": calendar[-1], "bars": len(calendar)},
        "exit": EXIT, "cost": COST, "portfolio": PORT,
        "strategies": {k: {"label": v["label"], "params": v["params"]} for k, v in STRATEGIES.items()},
        "results": results,
        "caveats": [
            "Rổ cặp là những cặp thanh khoản nhất HÔM NAY — thiên lệch người sống sót rất nặng "
            "với crypto, vì đồng chết thì biến mất khỏi danh sách.",
            "Nến 1h không cho biết trong một nến giá chạm cắt lỗ trước hay chốt lời trước; "
            "ở đây luôn giả định chạm cắt lỗ trước (phía bất lợi).",
            "Chưa tính funding nếu giao dịch hợp đồng vĩnh cửu, và chưa tính việc lệnh lớn "
            "không khớp hết ở altcoin thanh khoản mỏng.",
            "Nhiều chiến lược chạy trên cùng một đoạn dữ liệu: chọn cái tốt nhất sau khi đã thấy "
            "kết quả thì luôn đẹp hơn thực tế. Phải kiểm ngoài mẫu trước khi tin.",
        ],
    }
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\nXong sau {time.time()-t0:.0f}s → data/crypto-backtest.json", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
