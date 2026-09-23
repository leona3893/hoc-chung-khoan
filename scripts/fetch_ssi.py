#!/usr/bin/env python3
"""
Tải dữ liệu giá từ SSI iBoard, tính chỉ báo kỹ thuật và chấm điểm khuyến nghị.

Chỉ dùng thư viện chuẩn của Python (không cần pip install).

Đầu ra:
  data/analysis.json      – tổng quan thị trường + bảng điểm mọi mã (trang web đọc file này trước)
  data/bars/<MÃ>.json     – nến + chỉ báo của từng mã (tải khi người dùng bấm vào mã)

Chạy tay:   python scripts/fetch_ssi.py
Chạy nhanh: python scripts/fetch_ssi.py --only HPG,FPT   (chỉ vài mã, để thử)

Nguồn: https://iboard.ssi.com.vn  (API công khai, không cần đăng nhập)
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
BARS_DIR = os.path.join(DATA_DIR, "bars")
CFG_PATH = os.path.join(ROOT, "scripts", "watchlist.json")

API_CHART = "https://iboard-api.ssi.com.vn/statistics/charts/history"
API_STOCK_INFO = "https://iboard-api.ssi.com.vn/statistics/company/ssmi/stock-info"
API_PROFILE = "https://iboard-api.ssi.com.vn/statistics/company/ssmi/company-profile"
API_GROUP = "https://iboard-query.ssi.com.vn/stock/group/{}"
API_QUOTE = "https://iboard-query.ssi.com.vn/stock/{}"

VN_TZ = timezone(timedelta(hours=7))
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://iboard.ssi.com.vn",
    "Referer": "https://iboard.ssi.com.vn/",
}


# ----------------------------------------------------------------------------
# HTTP
# ----------------------------------------------------------------------------
def get_json(url, params=None, retries=3, pause=0.35):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read().decode("utf-8")
            time.sleep(pause)
            data = json.loads(body)
            if data.get("code") not in ("SUCCESS", None):
                raise RuntimeError(f"{data.get('code')}: {data.get('message')}")
            return data
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"Không lấy được {url}: {last}")


def fetch_history(symbol, days):
    now = int(time.time())
    d = get_json(API_CHART, {
        "resolution": "1D", "symbol": symbol,
        "from": now - days * 86400, "to": now,
    })["data"]
    bars = []
    for t, o, h, l, c, v in zip(d["t"], d["o"], d["h"], d["l"], d["c"], d["v"]):
        if c is None or c == 0:
            continue
        date = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
        bars.append([date, float(o), float(h), float(l), float(c), int(v or 0)])
    # loại nến trùng ngày (API đôi khi trả 2 bản ghi cùng phiên)
    dedup = {}
    for b in bars:
        dedup[b[0]] = b
    return [dedup[k] for k in sorted(dedup)]


def fetch_stock_info(symbol, days=40):
    to = datetime.now(VN_TZ)
    frm = to - timedelta(days=days)
    d = get_json(API_STOCK_INFO, {
        "symbol": symbol, "page": 1, "pageSize": 60,
        "fromDate": frm.strftime("%d/%m/%Y"), "toDate": to.strftime("%d/%m/%Y"),
    })["data"] or []
    rows = []
    for r in d:
        try:
            rows.append({
                "date": datetime.strptime(r["tradingDate"], "%d/%m/%Y").strftime("%Y-%m-%d"),
                "close": float(r["close"]), "ref": float(r["refPrice"]),
                "ceiling": float(r["ceilingPrice"]), "floor": float(r["floorPrice"]),
                "matchVal": float(r.get("totalMatchVal") or 0),
                "fBuyVol": float(r.get("foreignBuyVolTotal") or 0),
                "fSellVol": float(r.get("foreignSellVolTotal") or 0),
                "fBuyVal": float(r.get("foreignBuyValTotal") or 0),
                "fSellVal": float(r.get("foreignSellValTotal") or 0),
            })
        except (KeyError, ValueError):
            continue
    rows.sort(key=lambda x: x["date"])
    return rows


def fetch_profile(symbol):
    try:
        d = get_json(API_PROFILE, {"symbol": symbol})["data"] or {}
        return {"industry": d.get("industryName") or "", "sector": d.get("subSector") or d.get("sector") or ""}
    except Exception:  # noqa: BLE001
        return {"industry": "", "sector": ""}


def fetch_group(name):
    d = get_json(API_GROUP.format(name))["data"] or []
    out = []
    for r in d:
        if r.get("stockType") == "s":
            out.append({"symbol": r["stockSymbol"], "name": r.get("companyNameVi") or r.get("companyNameEn") or "",
                        "exchange": (r.get("exchange") or "").upper()})
    return out


def fetch_quote(symbol):
    d = get_json(API_QUOTE.format(symbol))["data"] or {}
    return {"name": d.get("companyNameVi") or d.get("companyNameEn") or symbol,
            "exchange": (d.get("exchange") or "").upper()}


# ----------------------------------------------------------------------------
# Chỉ báo (tất cả trả về list cùng độ dài với input, None khi chưa đủ dữ liệu)
# ----------------------------------------------------------------------------
def sma(xs, n):
    out, s = [None] * len(xs), 0.0
    for i, x in enumerate(xs):
        s += x
        if i >= n:
            s -= xs[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def ema(xs, n):
    out, k, prev = [None] * len(xs), 2.0 / (n + 1), None
    for i, x in enumerate(xs):
        if prev is None:
            if i >= n - 1:
                prev = sum(xs[: n]) / n
                out[i] = prev
            continue
        prev = x * k + prev * (1 - k)
        out[i] = prev
    return out


def rsi(closes, n=14):
    out = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    ag, al = gains / n, losses / n
    out[n] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (n - 1) + max(d, 0)) / n
        al = (al * (n - 1) + max(-d, 0)) / n
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def macd(closes, fast=12, slow=26, sig=9):
    ef, es = ema(closes, fast), ema(closes, slow)
    line = [None if (a is None or b is None) else a - b for a, b in zip(ef, es)]
    valid = [x for x in line if x is not None]
    sig_v = ema(valid, sig) if len(valid) >= sig else []
    signal = [None] * len(line)
    j = 0
    for i, x in enumerate(line):
        if x is not None:
            signal[i] = sig_v[j] if j < len(sig_v) else None
            j += 1
    hist = [None if (a is None or b is None) else a - b for a, b in zip(line, signal)]
    return line, signal, hist


def atr(bars, n=14):
    trs = []
    for i, b in enumerate(bars):
        h, l = b[2], b[3]
        if i == 0:
            trs.append(h - l)
        else:
            pc = bars[i - 1][4]
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    out, prev = [None] * len(bars), None
    for i, tr in enumerate(trs):
        if i == n - 1:
            prev = sum(trs[: n]) / n
            out[i] = prev
        elif i >= n:
            prev = (prev * (n - 1) + tr) / n
            out[i] = prev
    return out


def bollinger(closes, n=20, k=2.0):
    mid = sma(closes, n)
    up, lo = [None] * len(closes), [None] * len(closes)
    for i in range(n - 1, len(closes)):
        win = closes[i - n + 1: i + 1]
        m = mid[i]
        sd = math.sqrt(sum((x - m) ** 2 for x in win) / n)
        up[i], lo[i] = m + k * sd, m - k * sd
    return mid, up, lo


def swing_levels(bars, lookback=140, wing=5, tol=0.02):
    """Tìm đỉnh/đáy xoay (swing) trong `lookback` phiên gần nhất, gom các mức cách nhau < tol thành vùng."""
    seg = bars[-lookback:]
    highs, lows = [], []
    for i in range(wing, len(seg) - wing):
        h, l = seg[i][2], seg[i][3]
        if all(h >= seg[j][2] for j in range(i - wing, i + wing + 1)):
            highs.append(h)
        if all(l <= seg[j][3] for j in range(i - wing, i + wing + 1)):
            lows.append(l)

    def cluster(levels):
        levels = sorted(levels)
        groups = []
        for x in levels:
            if groups and abs(x - groups[-1][-1]) / groups[-1][-1] <= tol:
                groups[-1].append(x)
            else:
                groups.append([x])
        return [{"price": sum(g) / len(g), "touches": len(g)} for g in groups]

    return cluster(highs), cluster(lows)


def pct(a, b):
    return None if (a is None or b in (None, 0)) else (a / b - 1) * 100


def r2(x, d=2):
    return None if x is None else round(x, d)


def n0(x):
    """Số nguyên kiểu Việt: 27.312"""
    return "—" if x is None else f"{x:,.0f}".replace(",", ".")


def n1(x, plus=False):
    """Một chữ số thập phân kiểu Việt: 7,7 — plus=True thì thêm dấu + cho số dương."""
    if x is None:
        return "—"
    t = f"{abs(x):,.1f}".replace(",", "").replace(".", ",").replace("", ".")
    return ("-" if x < 0 else "+" if plus else "") + t


# ----------------------------------------------------------------------------
# Chấm điểm & khuyến nghị
# ----------------------------------------------------------------------------
REC_LABELS = [
    (45, "MUA", "buy", "Xu hướng tăng rõ và được khối lượng, động lượng xác nhận. Có thể giải ngân theo kế hoạch."),
    (20, "TÍCH LŨY", "acc", "Tín hiệu tích cực nhưng chưa đồng thuận. Mua thăm dò tỷ trọng nhỏ, chờ xác nhận để tăng."),
    (-20, "THEO DÕI", "hold", "Chưa có lợi thế rõ ràng. Nếu đang nắm giữ thì giữ theo kỷ luật cắt lỗ; chưa có thì đứng ngoài quan sát."),
    (-45, "GIẢM TỶ TRỌNG", "reduce", "Cấu trúc đang yếu đi. Hạ tỷ trọng ở nhịp hồi, không mua trung bình giá xuống."),
    (-101, "BÁN / ĐỨNG NGOÀI", "sell", "Xu hướng giảm được xác nhận. Không bắt đáy; chờ tín hiệu tạo đáy (MA20 cắt lên MA50, khối lượng cạn kiệt) mới xem lại."),
]


def label_for(score):
    for th, label, key, note in REC_LABELS:
        if score >= th:
            return label, key, note
    return REC_LABELS[-1][1:]


def analyze(symbol, bars, bench_bars, info_rows, meta, market_ok=True):
    closes = [b[4] for b in bars]
    vols = [b[5] for b in bars]
    n = len(bars)
    i = n - 1
    c = closes[i]

    s20, s50, s200 = sma(closes, 20), sma(closes, 50), sma(closes, 200)
    rs = rsi(closes)
    m_line, m_sig, m_hist = macd(closes)
    a14 = atr(bars)
    bb_mid, bb_up, bb_lo = bollinger(closes)
    v20 = sma(vols, 20)

    def at(arr, k=0):
        j = i - k
        return arr[j] if 0 <= j < len(arr) else None

    score = 0
    reasons = []  # (điểm, câu giải thích)
    setups = []

    # --- 1. Cấu trúc xu hướng (±30)
    ma20, ma50, ma200 = at(s20), at(s50), at(s200)
    t = 0
    if ma20 and ma50:
        if c > ma20 > ma50:
            t += 15
            reasons.append((+15, f"Giá nằm trên MA20 ({n0(ma20)}) và MA20 trên MA50 ({n0(ma50)}) — cấu trúc tăng ngắn hạn."))
        elif c < ma20 < ma50:
            t -= 15
            reasons.append((-15, f"Giá dưới MA20 ({n0(ma20)}) và MA20 dưới MA50 ({n0(ma50)}) — cấu trúc giảm ngắn hạn."))
        elif c > ma50:
            t += 6
            reasons.append((+6, "Giá trên MA50 nhưng MA20 chưa xác nhận — đang chuyển tiếp."))
        else:
            t -= 6
            reasons.append((-6, "Giá dưới MA50, xu hướng trung hạn chưa ủng hộ."))
    if ma200:
        if c > ma200:
            t += 8
            reasons.append((+8, f"Giá trên MA200 ({n0(ma200)}) — xu hướng dài hạn còn tăng."))
        else:
            t -= 8
            reasons.append((-8, f"Giá dưới MA200 ({n0(ma200)}) — xu hướng dài hạn đang giảm."))
    ma50_prev = at(s50, 10)
    if ma50 and ma50_prev:
        if ma50 > ma50_prev * 1.005:
            t += 7
            reasons.append((+7, "MA50 đang dốc lên."))
        elif ma50 < ma50_prev * 0.995:
            t -= 7
            reasons.append((-7, "MA50 đang dốc xuống."))
    score += max(-30, min(30, t))

    # Giao cắt MA20/MA50 trong 10 phiên gần nhất
    for k in range(1, 11):
        a0, b0, a1, b1 = at(s20, k - 1), at(s50, k - 1), at(s20, k), at(s50, k)
        if None in (a0, b0, a1, b1):
            break
        if a1 <= b1 and a0 > b0:
            setups.append({"key": "golden", "text": f"MA20 vừa cắt lên MA50 ({k} phiên trước) — tín hiệu bắt đầu xu hướng tăng."})
            break
        if a1 >= b1 and a0 < b0:
            setups.append({"key": "death", "text": f"MA20 vừa cắt xuống MA50 ({k} phiên trước) — cảnh báo đảo chiều giảm."})
            break

    # --- 2. Động lượng: MACD + RSI (±20)
    mo = 0
    h0, h1 = at(m_hist), at(m_hist, 1)
    if h0 is not None and h1 is not None:
        if h0 > 0:
            mo += 7 if h0 >= h1 else 4
            reasons.append((mo, "MACD trên đường tín hiệu" + (", histogram đang mở rộng." if h0 >= h1 else " nhưng histogram đang thu hẹp.")))
        else:
            d = -7 if h0 <= h1 else -4
            mo += d
            reasons.append((d, "MACD dưới đường tín hiệu" + (", động lượng giảm còn mạnh." if h0 <= h1 else " nhưng đang bớt tiêu cực.")))
    r0 = at(rs)
    if r0 is not None:
        if 55 <= r0 <= 70:
            mo += 8
            reasons.append((+8, f"RSI {r0:.0f} — vùng động lượng tích cực, chưa quá mua."))
        elif 70 < r0 <= 80:
            mo += 3
            reasons.append((+3, f"RSI {r0:.0f} — mạnh nhưng đã vào vùng quá mua, hạn chế mua đuổi."))
        elif r0 > 80:
            mo -= 4
            reasons.append((-4, f"RSI {r0:.0f} — quá mua cực đoan, rủi ro điều chỉnh cao."))
        elif 45 <= r0 < 55:
            reasons.append((0, f"RSI {r0:.0f} — trung tính."))
        elif 30 <= r0 < 45:
            mo -= 6
            reasons.append((-6, f"RSI {r0:.0f} — động lượng yếu."))
        else:
            mo -= 3
            reasons.append((-3, f"RSI {r0:.0f} — quá bán; có thể hồi kỹ thuật nhưng chưa phải tín hiệu mua."))
            setups.append({"key": "oversold", "text": f"RSI {r0:.0f} dưới 30: theo dõi nến đảo chiều kèm khối lượng để bắt nhịp hồi ngắn."})
    score += max(-20, min(20, mo))

    # --- 3. Khối lượng xác nhận (±15)
    vo = 0
    va = at(v20)
    if va and va > 0:
        up_big = down_big = 0
        for k in range(0, 10):
            b = bars[i - k]
            vv = v20[i - k]
            if not vv:
                continue
            if b[5] > 1.3 * vv:
                if b[4] > b[1]:
                    up_big += 1
                elif b[4] < b[1]:
                    down_big += 1
        vo = max(-15, min(15, (up_big - down_big) * 5))
        if vo > 0:
            reasons.append((vo, f"10 phiên gần nhất có {up_big} phiên tăng với khối lượng đột biến (>130% trung bình) so với {down_big} phiên giảm — tiền vào."))
        elif vo < 0:
            reasons.append((vo, f"10 phiên gần nhất có {down_big} phiên giảm với khối lượng đột biến so với {up_big} phiên tăng — áp lực bán chủ động."))
        else:
            reasons.append((0, "Khối lượng chưa cho tín hiệu rõ ràng về bên đang chủ động."))
        vratio = bars[i][5] / va
        if vratio >= 2 and c > bars[i][1]:
            setups.append({"key": "volspike", "text": f"Phiên gần nhất khối lượng gấp {n1(vratio)} lần trung bình 20 phiên và đóng cửa tăng — cần theo dõi có tiếp diễn không."})
    score += vo

    # --- 4. Sức mạnh tương đối so với VN-Index (±15)
    rsx = 0
    if bench_bars and n > 63 and len(bench_bars) > 63:
        r_sym = pct(c, closes[i - 63])
        r_bm = pct(bench_bars[-1][4], bench_bars[-64][4])
        if r_sym is not None and r_bm is not None:
            diff = r_sym - r_bm
            rsx = max(-15, min(15, round(diff * 1.2)))
            if rsx >= 5:
                reasons.append((rsx, f"3 tháng qua mã này {n1(r_sym, True)}% so với VN-Index {n1(r_bm, True)}% — mạnh hơn thị trường."))
            elif rsx <= -5:
                reasons.append((rsx, f"3 tháng qua mã này {n1(r_sym, True)}% so với VN-Index {n1(r_bm, True)}% — yếu hơn thị trường."))
            else:
                reasons.append((rsx, f"3 tháng qua đi cùng nhịp với VN-Index ({n1(r_sym, True)}% so với {n1(r_bm, True)}%)."))
    score += rsx

    # --- 5. Khối ngoại 20 phiên (±10)
    fx = 0
    foreign = {"net5": None, "net20": None, "buy20": None, "sell20": None}
    if info_rows:
        last20 = info_rows[-20:]
        last5 = info_rows[-5:]
        net20 = sum(r["fBuyVal"] - r["fSellVal"] for r in last20)
        net5 = sum(r["fBuyVal"] - r["fSellVal"] for r in last5)
        buy20 = sum(r["fBuyVal"] for r in last20)
        sell20 = sum(r["fSellVal"] for r in last20)
        foreign = {"net5": net5, "net20": net20, "buy20": buy20, "sell20": sell20}
        turnover20 = sum(r["matchVal"] for r in last20) or 1
        share = net20 / turnover20 * 100  # % giá trị giao dịch
        fx = max(-10, min(10, round(share * 4)))
        ty = net20 / 1e9
        if fx >= 3:
            reasons.append((fx, f"Khối ngoại mua ròng {n0(ty)} tỷ trong 20 phiên."))
        elif fx <= -3:
            reasons.append((fx, f"Khối ngoại bán ròng {n0(abs(ty))} tỷ trong 20 phiên."))
        else:
            reasons.append((fx, f"Khối ngoại giao dịch cân bằng ({n1(ty, True)} tỷ / 20 phiên)."))
    score += fx

    # --- 6. Vị trí trong biên 52 tuần (±10)
    px = 0
    win = bars[-250:]
    hi52 = max(b[2] for b in win)
    lo52 = min(b[3] for b in win)
    if hi52 > lo52:
        pos = (c - lo52) / (hi52 - lo52)  # 0..1
        px = round((pos - 0.5) * 20)
        d_hi = pct(c, hi52)
        if pos >= 0.9:
            reasons.append((px, f"Giá cách đỉnh 52 tuần chỉ {n1(abs(d_hi))}% — sức mạnh giá cao, nhưng vùng đỉnh cũ là kháng cự."))
        elif pos <= 0.15:
            reasons.append((px, f"Giá gần đáy 52 tuần ({n0(lo52)}) — yếu về giá; chỉ hấp dẫn nếu có tín hiệu tạo đáy."))
        else:
            reasons.append((px, f"Giá ở {pos*100:.0f}% biên 52 tuần ({n0(lo52)} – {n0(hi52)})."))
    score += px

    # --- 7. Phanh rủi ro ngắn hạn (−25…0): chặn trường hợp "chỉ báo còn đẹp nhưng giá đang sụp"
    brake = 0
    hi10 = max(b[2] for b in bars[-11:-1]) if n > 11 else c
    dd = pct(c, hi10) or 0
    if dd <= -12:
        brake -= 12
        reasons.append((-12, f"Giá đã rơi {n1(abs(dd))}% từ đỉnh 10 phiên ({n0(hi10)}) — nhịp giảm còn mới, chỉ báo chậm chưa phản ánh hết."))
    elif dd <= -7:
        brake -= 6
        reasons.append((-6, f"Giá lùi {n1(abs(dd))}% từ đỉnh 10 phiên ({n0(hi10)}) — đang trong nhịp điều chỉnh."))
    hard = 0
    for k in range(0, 3):
        if i - k - 1 < 0:
            break
        d = pct(closes[i - k], closes[i - k - 1]) or 0
        if d <= -6.5:
            hard += 1
    if hard:
        brake -= 8 * hard
        reasons.append((-8 * hard, f"Có {hard} phiên giảm sàn (hoặc gần sàn) trong 3 phiên gần nhất — bên bán đang áp đảo dứt khoát."))
        setups.append({"key": "death", "text": "Giá vừa giảm sàn: đứng ngoài cho tới khi xuất hiện phiên cân bằng (đóng cửa trên giá mở, khối lượng cạn dần)."})
    if ma20 and pct(c, ma20) and pct(c, ma20) > 20:
        brake -= 5
        reasons.append((-5, f"Giá cao hơn MA20 tới {pct(c, ma20):.0f}% — đã đi quá xa đường trung bình, rủi ro hồi về cao."))
    brake = max(-25, brake)
    score += brake

    score = max(-100, min(100, score))
    # Đang giảm sàn hoặc rơi sâu thì không thể là khuyến nghị MUA, bất kể điểm
    if (hard or dd <= -12) and score > 19:
        score = 19

    # --- Điều chỉnh theo bối cảnh thị trường
    market_note = None
    if not market_ok and score > 30:
        market_note = "VN-Index đang trong xu hướng giảm nên hạ một bậc: chỉ mua thăm dò, giữ tỷ trọng thấp."
        score = 30

    label, key, note = label_for(score)

    # --- Hỗ trợ / kháng cự & kế hoạch giao dịch
    res_lv, sup_lv = swing_levels(bars)
    res_above = sorted([x for x in res_lv if x["price"] > c * 1.005], key=lambda x: x["price"])
    sup_below = sorted([x for x in sup_lv if x["price"] < c * 0.995], key=lambda x: -x["price"])
    a = at(a14) or (c * 0.02)
    nearest_sup = sup_below[0]["price"] if sup_below else None
    nearest_res = res_above[0]["price"] if res_above else None

    stop_struct = min(nearest_sup * 0.97 if nearest_sup else c - 2 * a, c - 2 * a)
    stop = max(stop_struct, c - 3.5 * a, c * 0.90)  # không để cắt lỗ quá xa: tối đa 10% hoặc 3,5×ATR
    stop_capped = stop > stop_struct + 1  # hỗ trợ cấu trúc nằm quá xa, phải cắt lỗ theo % vốn
    target = nearest_res if nearest_res else c + 3 * a
    if nearest_res and pct(nearest_res, c) < 4 and len(res_above) > 1:
        target = res_above[1]["price"]  # kháng cự sát quá thì nhìn tới mức kế
    risk = c - stop
    reward = target - c
    rr = round(reward / risk, 2) if risk > 0 else None
    entry_lo = max(nearest_sup, ma20) if (nearest_sup and ma20 and ma20 < c) else (ma20 if ma20 and ma20 < c else c * 0.98)
    entry_lo = max(entry_lo, stop * 1.02)  # vùng mua luôn phải nằm trên điểm cắt lỗ
    entry = {"lo": min(entry_lo, c), "hi": c}

    if stop_capped:
        note += (f" Giá hiện cách hỗ trợ gần nhất ({n0(nearest_sup)}) tới {abs(pct(nearest_sup, c)):.0f}%, "
                 f"nên điểm cắt lỗ {n0(stop)} đặt theo giới hạn thua lỗ 10% chứ không dựa vào cấu trúc giá — "
                 f"khả năng bị quét lệnh cao hơn bình thường." if nearest_sup else
                 " Chưa có hỗ trợ rõ ràng bên dưới, cắt lỗ phải đặt theo giới hạn thua lỗ 10%.")
    if rr is not None and rr < 1.5 and key in ("buy", "acc"):
        note += f" Tỷ lệ lời/lỗ hiện chỉ {n1(rr)}:1 (dưới 1,5) — chờ giá lùi về vùng {n0(entry['lo'])} hoặc vượt kháng cự {n0(target)} kèm khối lượng rồi mới vào."

    # Setup: hồi về MA20 trong xu hướng tăng / vượt kháng cự
    ma50_rising = bool(ma50 and ma50_prev and ma50 > ma50_prev)
    if ma20 and ma50 and ma20 > ma50 and ma50_rising and abs(pct(c, ma20)) <= 2 and c > ma50:
        setups.append({"key": "pullback", "text": f"Giá đang test lại MA20 ({n0(ma20)}) trong xu hướng tăng — điểm vào có lợi thế nếu nến tiếp theo giữ được MA20."})
    if len(bars) > 25:
        prior_high = max(b[2] for b in bars[-25:-1])
        if c > prior_high and va and bars[i][5] > 1.3 * va:
            setups.append({"key": "breakout", "text": f"Đóng cửa vượt đỉnh 24 phiên ({n0(prior_high)}) với khối lượng cao — tín hiệu bứt phá."})
    if bb_up[i] and c > bb_up[i]:
        setups.append({"key": "bbup", "text": "Giá đóng ngoài dải Bollinger trên — hưng phấn ngắn hạn, thường kèm điều chỉnh vài phiên."})
    if bb_lo[i] and c < bb_lo[i]:
        setups.append({"key": "bblo", "text": "Giá đóng dưới dải Bollinger dưới — bán quá đà ngắn hạn."})

    # Xu hướng (chữ)
    if ma50 and ma200:
        if c > ma50 > ma200:
            trend = "Tăng"
        elif c < ma50 < ma200:
            trend = "Giảm"
        else:
            trend = "Đi ngang"
    elif ma50:
        trend = "Tăng" if c > ma50 else "Giảm"
    else:
        trend = "—"

    prev_c = closes[i - 1] if i > 0 else c
    ref = info_rows[-1]["ref"] if info_rows and info_rows[-1]["date"] == bars[i][0] else prev_c
    out = {
        "symbol": symbol,
        "name": meta.get("name", symbol),
        "exchange": meta.get("exchange", ""),
        "industry": meta.get("industry", ""),
        "date": bars[i][0],
        "close": c, "ref": ref,
        "chg": r2(c - ref, 0), "chgPct": r2(pct(c, ref)),
        "vol": bars[i][5], "volAvg20": r2(va, 0),
        "volRatio": r2(bars[i][5] / va, 2) if va else None,
        "ret": {"1w": r2(pct(c, closes[i - 5])) if n > 5 else None,
                "1m": r2(pct(c, closes[i - 21])) if n > 21 else None,
                "3m": r2(pct(c, closes[i - 63])) if n > 63 else None,
                "ytd": None},
        "ind": {"ma20": r2(ma20, 0), "ma50": r2(ma50, 0), "ma200": r2(ma200, 0),
                "rsi": r2(r0, 1), "macd": r2(at(m_line), 0), "macdSig": r2(at(m_sig), 0), "macdHist": r2(h0, 0),
                "atr": r2(a, 0), "bbUp": r2(bb_up[i], 0), "bbLo": r2(bb_lo[i], 0),
                "hi52": hi52, "lo52": lo52},
        "trend": trend,
        "levels": {"support": [{"price": round(x["price"]), "touches": x["touches"]} for x in sup_below[:3]],
                   "resistance": [{"price": round(x["price"]), "touches": x["touches"]} for x in res_above[:3]]},
        "foreign": {k: (None if v is None else round(v)) for k, v in foreign.items()},
        "score": int(round(score)),
        "rec": label, "recKey": key, "recNote": note,
        "marketNote": market_note,
        "reasons": [{"pts": p, "text": s} for p, s in sorted(reasons, key=lambda x: -abs(x[0]))],
        "setups": setups,
        "plan": {"entryLo": round(entry["lo"]), "entryHi": round(entry["hi"]),
                 "stop": round(stop), "target": round(target), "rr": rr,
                 "riskPct": r2(pct(stop, c)), "rewardPct": r2(pct(target, c))},
    }

    # YTD
    year = bars[i][0][:4]
    first_of_year = next((b for b in bars if b[0][:4] == year), None)
    if first_of_year and first_of_year is not bars[i]:
        out["ret"]["ytd"] = r2(pct(c, first_of_year[4]))

    series = {
        "symbol": symbol, "date": bars[i][0],
        "bars": bars[-KEEP:],
        "ma20": [r2(x, 0) for x in s20[-KEEP:]], "ma50": [r2(x, 0) for x in s50[-KEEP:]], "ma200": [r2(x, 0) for x in s200[-KEEP:]],
        "rsi": [r2(x, 1) for x in rs[-KEEP:]],
        "macd": [r2(x, 0) for x in m_line[-KEEP:]], "macdSig": [r2(x, 0) for x in m_sig[-KEEP:]], "macdHist": [r2(x, 0) for x in m_hist[-KEEP:]],
        "bbUp": [r2(x, 0) for x in bb_up[-KEEP:]], "bbLo": [r2(x, 0) for x in bb_lo[-KEEP:]],
        "volAvg20": [r2(x, 0) for x in v20[-KEEP:]],
        "foreign": [{"date": r["date"], "net": round(r["fBuyVal"] - r["fSellVal"])} for r in info_rows[-KEEP:]],
        "levels": out["levels"],
    }
    return out, series


def analyze_index(symbol, bars):
    closes = [b[4] for b in bars]
    i = len(bars) - 1
    c = closes[i]
    s20, s50, s200 = sma(closes, 20), sma(closes, 50), sma(closes, 200)
    rs = rsi(closes)
    m_line, m_sig, m_hist = macd(closes)
    ma20, ma50, ma200 = s20[i], s50[i], s200[i]
    if ma50 and ma200:
        trend = "Tăng" if c > ma50 > ma200 else ("Giảm" if c < ma50 < ma200 else "Đi ngang")
    else:
        trend = "Tăng" if (ma50 and c > ma50) else "Giảm"
    ok = bool(ma50 and c > ma50)
    out = {
        "symbol": symbol, "date": bars[i][0], "close": c,
        "chg": r2(c - closes[i - 1], 2), "chgPct": r2(pct(c, closes[i - 1])),
        "ret": {"1w": r2(pct(c, closes[i - 5])), "1m": r2(pct(c, closes[i - 21])), "3m": r2(pct(c, closes[i - 63])) if i > 63 else None},
        "ind": {"ma20": r2(ma20), "ma50": r2(ma50), "ma200": r2(ma200), "rsi": r2(rs[i], 1), "macdHist": r2(m_hist[i], 2)},
        "trend": trend, "aboveMa50": ok,
    }
    series = {
        "symbol": symbol, "date": bars[i][0], "bars": bars[-KEEP:],
        "ma20": [r2(x) for x in s20[-KEEP:]], "ma50": [r2(x) for x in s50[-KEEP:]], "ma200": [r2(x) for x in s200[-KEEP:]],
        "rsi": [r2(x, 1) for x in rs[-KEEP:]],
        "macd": [r2(x, 2) for x in m_line[-KEEP:]], "macdSig": [r2(x, 2) for x in m_sig[-KEEP:]], "macdHist": [r2(x, 2) for x in m_hist[-KEEP:]],
        "bbUp": [None] * min(KEEP, len(bars)), "bbLo": [None] * min(KEEP, len(bars)),
        "volAvg20": [r2(x, 0) for x in sma([b[5] for b in bars], 20)[-KEEP:]],
        "foreign": [], "levels": {"support": [], "resistance": []},
    }
    return out, series


# ----------------------------------------------------------------------------
KEEP = 260


def main():
    global KEEP
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="chỉ chạy các mã này, cách nhau bằng dấu phẩy")
    args = ap.parse_args()

    with open(CFG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    KEEP = int(cfg.get("bars_keep", 260))
    days = int(cfg.get("history_days", 800))
    bench = cfg.get("benchmark", "VNINDEX")

    os.makedirs(BARS_DIR, exist_ok=True)

    # 1. Danh sách mã
    universe = {}
    for g in cfg.get("groups", []):
        try:
            for r in fetch_group(g):
                universe.setdefault(r["symbol"], r)
                universe[r["symbol"]].setdefault("groups", []).append(g)
            print(f"[nhóm] {g}: {len(universe)} mã", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print(f"[lỗi] nhóm {g}: {e}", file=sys.stderr)
    for s in cfg.get("extra", []):
        if s not in universe:
            try:
                q = fetch_quote(s)
                universe[s] = {"symbol": s, "name": q["name"], "exchange": q["exchange"], "groups": []}
            except Exception as e:  # noqa: BLE001
                print(f"[lỗi] mã {s}: {e}", file=sys.stderr)
    symbols = sorted(universe)
    if args.only:
        keep = {x.strip().upper() for x in args.only.split(",")}
        symbols = [s for s in symbols if s in keep]

    # 2. Chỉ số
    indices, bench_bars = {}, None
    for idx in cfg.get("indices", []):
        try:
            b = fetch_history(idx, days)
            summ, series = analyze_index(idx, b)
            indices[idx] = summ
            with open(os.path.join(BARS_DIR, f"{idx}.json"), "w", encoding="utf-8") as f:
                json.dump(series, f, ensure_ascii=False, separators=(",", ":"))
            if idx == bench:
                bench_bars = b
            print(f"[chỉ số] {idx}: {len(b)} phiên, đóng cửa {b[-1][4]}", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print(f"[lỗi] chỉ số {idx}: {e}", file=sys.stderr)

    market_ok = indices.get(bench, {}).get("aboveMa50", True)

    # 3. Từng mã
    results, errors = [], []
    for s in symbols:
        try:
            bars = fetch_history(s, days)
            if len(bars) < 60:
                raise RuntimeError(f"chỉ có {len(bars)} phiên")
            # giá lịch sử tính bằng nghìn đồng → đổi về đồng cho khớp bảng điện
            if bars[-1][4] < 1000:
                bars = [[b[0], b[1] * 1000, b[2] * 1000, b[3] * 1000, b[4] * 1000, b[5]] for b in bars]
            info = fetch_stock_info(s)
            meta = dict(universe[s])
            meta.update(fetch_profile(s))
            summ, series = analyze(s, bars, bench_bars, info, meta, market_ok)
            results.append(summ)
            with open(os.path.join(BARS_DIR, f"{s}.json"), "w", encoding="utf-8") as f:
                json.dump(series, f, ensure_ascii=False, separators=(",", ":"))
            print(f"[{s}] {summ['close']:,.0f} ({summ['chgPct']:+.2f}%) điểm {summ['score']:+d} → {summ['rec']}", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            errors.append({"symbol": s, "error": str(e)})
            print(f"[lỗi] {s}: {e}", file=sys.stderr)

    results.sort(key=lambda x: -x["score"])

    # 4. Độ rộng thị trường
    n = len(results) or 1
    breadth = {
        "count": len(results),
        "aboveMa20": sum(1 for r in results if r["ind"]["ma20"] and r["close"] > r["ind"]["ma20"]),
        "aboveMa50": sum(1 for r in results if r["ind"]["ma50"] and r["close"] > r["ind"]["ma50"]),
        "aboveMa200": sum(1 for r in results if r["ind"]["ma200"] and r["close"] > r["ind"]["ma200"]),
        "up": sum(1 for r in results if (r["chg"] or 0) > 0),
        "down": sum(1 for r in results if (r["chg"] or 0) < 0),
        "buy": sum(1 for r in results if r["recKey"] in ("buy", "acc")),
        "sell": sum(1 for r in results if r["recKey"] in ("sell", "reduce")),
    }
    bm = indices.get(bench, {})
    pct50 = breadth["aboveMa50"] / n * 100
    if bm.get("trend") == "Tăng" and pct50 >= 60:
        regime, regime_note = "Thuận lợi", "VN-Index trong xu hướng tăng và đa số cổ phiếu lớn trên MA50. Ưu tiên mua theo xu hướng, giữ tỷ trọng cổ phiếu cao."
    elif bm.get("trend") == "Giảm" or pct50 < 35:
        regime, regime_note = "Bất lợi", "VN-Index dưới MA50 hoặc độ rộng yếu. Giữ nhiều tiền mặt, chỉ giao dịch thăm dò với cắt lỗ chặt."
    else:
        regime, regime_note = "Trung tính", "Thị trường phân hoá. Chọn lọc mã có sức mạnh tương đối cao, tỷ trọng vừa phải."

    analysis = {
        "updatedAt": datetime.now(VN_TZ).strftime("%Y-%m-%d %H:%M"),
        "dataDate": bm.get("date") or (results[0]["date"] if results else None),
        "source": "SSI iBoard (iboard.ssi.com.vn)",
        "watchlist": {"groups": cfg.get("groups", []), "extra": cfg.get("extra", [])},
        "market": {"regime": regime, "regimeNote": regime_note, "breadth": breadth, "indices": indices},
        "symbols": results,
        "errors": errors,
    }
    with open(os.path.join(DATA_DIR, "analysis.json"), "w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\nXong: {len(results)} mã, {len(errors)} lỗi. Thị trường: {regime}.", file=sys.stderr)


if __name__ == "__main__":
    main()
