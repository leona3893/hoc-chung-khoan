#!/usr/bin/env python3
"""
Vẽ ảnh chart kèm theo mỗi tín hiệu mua/bán, để gửi lên Telegram.

Dùng Pillow. Đây là thư viện ngoài duy nhất của cả repo — mọi script khác chỉ dùng
thư viện chuẩn. Không có Pillow thì bot vẫn chạy, chỉ gửi tin chữ không có ảnh.

    python scripts/crypto_chart.py BTCUSDT 4h   # vẽ thử một ảnh mẫu ra scratch/
"""

import os
import sys
from datetime import datetime, timedelta, timezone

try:
    from PIL import Image, ImageDraw, ImageFont
    HAVE_PIL = True
except ImportError:  # noqa: BLE001
    HAVE_PIL = False

VN_TZ = timezone(timedelta(hours=7))

# Màu nền tối, giống bảng giá sàn
BG = (14, 17, 22)
PANEL = (20, 24, 31)
GRID = (36, 42, 52)
TEXT = (226, 232, 240)
MUTED = (122, 134, 150)
UP = (38, 194, 129)
DOWN = (237, 83, 80)
ACCENT = (240, 185, 11)
TP_FILL = (38, 194, 129, 28)
SL_FILL = (237, 83, 80, 28)
TRAIL = (240, 185, 11)

W, H = 1000, 620
PAD_L, PAD_R, PAD_T = 14, 92, 56
PRICE_H = 360
VOL_H = 90
GAP = 18


def font(size, bold=False):
    names = (["segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"] if bold
             else ["segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"])
    roots = ["C:/Windows/Fonts/", "/usr/share/fonts/truetype/dejavu/",
             "/usr/share/fonts/truetype/liberation/", ""]
    for r in roots:
        for n in names:
            try:
                return ImageFont.truetype(r + n, size)
            except Exception:  # noqa: BLE001
                continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def fmt(p):
    if p is None:
        return "—"
    if p >= 1000:
        return f"{p:,.0f}"
    if p >= 1:
        return f"{p:,.3f}".rstrip("0").rstrip(".")
    return f"{p:.6f}".rstrip("0")


def sma(xs, n):
    out, s = [None] * len(xs), 0.0
    for i, x in enumerate(xs):
        s += x
        if i >= n:
            s -= xs[i - n]
        out[i] = s / n if i >= n - 1 else None
    return out


def render(bars, meta, path, window=70):
    """bars: [[ts,o,h,l,c,v], ...]  meta: thông tin lệnh. Trả về path hoặc None."""
    if not HAVE_PIL or len(bars) < 20:
        return None

    seg = bars[-window:]
    n = len(seg)
    entry = meta.get("entry")
    tp, sl = meta.get("tp"), meta.get("stop0") or meta.get("stop")
    side = meta.get("side", "BUY")

    # --- thang giá, tính cả vùng TP/SL để không bị cắt mất
    lows = [b[3] for b in seg] + [x for x in (sl,) if x]
    highs = [b[2] for b in seg] + [x for x in (tp,) if x]
    lo, hi = min(lows), max(highs)
    pad = (hi - lo) * 0.08 or hi * 0.01
    lo, hi = lo - pad, hi + pad

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img, "RGBA")
    f_title, f_sub, f_lbl, f_sm = font(19, True), font(13), font(13), font(11)

    plot_w = W - PAD_L - PAD_R
    # Chừa một khoảng trống bên phải để vẽ vùng chốt lời / cắt lỗ. Không có nó thì
    # lệnh vừa vào (nến cuối) chỉ còn một vạch mỏng sát mép, không đọc được gì.
    proj_w = plot_w * 0.26
    cand_w = plot_w - proj_w
    y0, y1 = PAD_T, PAD_T + PRICE_H
    vy0, vy1 = y1 + GAP, y1 + GAP + VOL_H

    def px(i):
        return PAD_L + cand_w * (i + 0.5) / n

    def py(p):
        return y1 - (p - lo) / (hi - lo) * (y1 - y0)

    # --- tiêu đề
    sym = meta.get("symbol", "").replace("USDT", "/USDT")
    col = UP if side == "BUY" else (UP if (meta.get("pnlPct") or 0) >= 0 else DOWN)
    d.text((PAD_L, 12), f"{side} {sym}", font=f_title, fill=col)
    head = f"{meta.get('interval', '4h')} · vào {fmt(entry)}"
    if side == "SELL":
        head += f" · ra {fmt(meta.get('exitPrice'))} · {meta.get('pnlPct', 0):+.2f}%"
    d.text((PAD_L + d.textlength(f"{side} {sym}", font=f_title) + 14, 16), head,
           font=f_sub, fill=MUTED)
    # Chiến lược theo xu hướng không có cắt lỗ %, chốt lời hay hạn giữ — chỉ ghi
    # những phần thực sự có, đừng định dạng giá trị rỗng.
    ex = meta.get("exits", {})
    bits = []
    if ex.get("slPct"):
        bits.append(f"SL −{ex['slPct']:.0f}%")
    if ex.get("tpPct"):
        bits.append(f"TP +{ex['tpPct']:.0f}%")
    if ex.get("trailPct"):
        bits.append(f"trail {ex['trailPct']:.0f}%")
    if ex.get("maxHold"):
        bits.append(f"giữ tối đa {ex['maxHold']}h")
    if sl and entry:
        bits.append(f"ra khi thủng {fmt(sl)}") if not ex.get("slPct") else None
    if meta.get("strategy"):
        bits.append(str(meta["strategy"]))
    sub = " · ".join(b for b in bits if b)
    d.text((PAD_L, 34), sub, font=f_sm, fill=MUTED)

    d.rectangle([PAD_L, y0, W - PAD_R, y1], fill=PANEL)
    d.rectangle([PAD_L, vy0, W - PAD_R, vy1], fill=PANEL)

    # --- lưới giá
    step = (hi - lo) / 5
    mag = 10 ** (len(str(int(step))) - 1) if step >= 1 else 10 ** -(len(str(step).split(".")[1]) - len(str(step).split(".")[1].lstrip("0")) + 1)
    step = max(mag, round(step / mag) * mag)
    g = (int(lo / step) + 1) * step
    while g < hi:
        yy = py(g)
        d.line([PAD_L, yy, W - PAD_R, yy], fill=GRID)
        d.text((W - PAD_R + 6, yy - 7), fmt(g), font=f_sm, fill=MUTED)
        g += step

    def tag(y, text, color):
        """Nhãn ở lề phải, có nền để không đè lên nhãn lưới."""
        w = d.textlength(text, font=f_sm)
        d.rectangle([W - PAD_R + 3, y - 8, W - PAD_R + 9 + w, y + 8], fill=BG)
        d.text((W - PAD_R + 6, y - 7), text, font=f_sm, fill=color)

    # ranh giới "hiện tại": bên phải là phần chiếu tới, chưa có giá
    nowx = PAD_L + cand_w
    for yy in range(int(y0), int(vy1), 7):
        d.line([nowx, yy, nowx, yy + 3], fill=GRID)

    # --- vùng chốt lời / cắt lỗ, kéo từ nến vào lệnh sang phải
    ei = meta.get("entryIdx")
    if ei is None:
        ei = n - 1
    ex_px = px(ei)
    if entry:
        if tp:
            d.rectangle([ex_px, py(tp), W - PAD_R, py(entry)], fill=TP_FILL)
            d.line([ex_px, py(tp), W - PAD_R, py(tp)], fill=UP)
            tag(py(tp), f"TP {fmt(tp)}", UP)
        if sl:
            d.rectangle([ex_px, py(entry), W - PAD_R, py(sl)], fill=SL_FILL)
            d.line([ex_px, py(sl), W - PAD_R, py(sl)], fill=DOWN)
            tag(py(sl), f"SL {fmt(sl)}", DOWN)
        d.line([ex_px, py(entry), W - PAD_R, py(entry)], fill=TEXT)
        tag(py(entry), fmt(entry), TEXT)

    # --- đường cắt lỗ dời theo đỉnh (vẽ lại từ chính nến, không cần lưu thêm gì)
    trail_pct = ex.get("trailPct")
    if trail_pct and ei < n - 1 and sl:
        peak, pts = seg[ei][2], []
        stop = sl
        for i in range(ei, n):
            peak = max(peak, seg[i][2])
            stop = max(stop, peak * (1 - trail_pct / 100))
            pts.append((px(i), py(stop)))
        for k in range(1, len(pts)):
            d.line([pts[k - 1][0], pts[k - 1][1], pts[k][0], pts[k][1]], fill=TRAIL, width=1)
            d.line([pts[k][0], pts[k - 1][1], pts[k][0], pts[k][1]], fill=TRAIL, width=1)

    # --- MA14
    ma = sma([b[4] for b in seg], 14)
    prev = None
    for i, m in enumerate(ma):
        if m is None:
            continue
        if prev:
            d.line([prev[0], prev[1], px(i), py(m)], fill=(90, 150, 220), width=2)
        prev = (px(i), py(m))

    # --- nến
    bw = max(2, plot_w / n * 0.62)
    for i, b in enumerate(seg):
        c = UP if b[4] >= b[1] else DOWN
        x = px(i)
        d.line([x, py(b[2]), x, py(b[3])], fill=c, width=1)
        top, bot = py(max(b[1], b[4])), py(min(b[1], b[4]))
        d.rectangle([x - bw / 2, top, x + bw / 2, max(bot, top + 1)], fill=c)

    # --- mốc vào / ra lệnh
    def marker(i, up, color, label):
        x, yy = px(i), py(seg[i][3] if up else seg[i][2])
        off = 12 if up else -12
        tri = [(x, yy + off * 0.5), (x - 6, yy + off * 1.4), (x + 6, yy + off * 1.4)]
        d.polygon(tri, fill=color)
        d.text((x - d.textlength(label, font=f_sm) / 2, yy + off * 1.4 + (4 if up else -16)),
               label, font=f_sm, fill=color)

    if 0 <= ei < n:
        marker(ei, True, UP, "MUA")
    if side == "SELL" and meta.get("exitPrice"):
        xx, yy = px(n - 1), py(meta["exitPrice"])
        c = DOWN if (meta.get("pnlPct") or 0) < 0 else UP
        d.polygon([(xx, yy), (xx - 11, yy - 7), (xx - 11, yy + 7)], fill=c)
        lbl = f"BÁN {meta.get('pnlPct', 0):+.2f}%"
        lw = d.textlength(lbl, font=f_sm)
        d.rectangle([xx - 15 - lw - 6, yy - 9, xx - 13, yy + 9], fill=BG)
        d.text((xx - 15 - lw, yy - 7), lbl, font=f_sm, fill=c)

    # --- khối lượng
    vmax = max(b[5] for b in seg) or 1
    vavg = sma([b[5] for b in seg], 20)
    for i, b in enumerate(seg):
        c = UP if b[4] >= b[1] else DOWN
        vh = b[5] / vmax * (vy1 - vy0 - 6)
        d.rectangle([px(i) - bw / 2, vy1 - vh, px(i) + bw / 2, vy1], fill=c + (150,))
    if vavg[-1]:
        yy = vy1 - (vavg[-1] * 2.5 / vmax) * (vy1 - vy0 - 6)
        if yy > vy0:
            for x in range(PAD_L, W - PAD_R, 8):
                d.line([x, yy, x + 4, yy], fill=ACCENT)
            d.text((W - PAD_R + 6, yy - 7), "KL ×2,5", font=f_sm, fill=ACCENT)
    d.text((PAD_L, vy0 - 15), "KHỐI LƯỢNG", font=f_sm, fill=MUTED)

    # --- trục thời gian
    for i in range(0, n, max(1, n // 6)):
        t = datetime.fromtimestamp(seg[i][0] / 1000, VN_TZ)
        d.text((px(i) - 16, vy1 + 8), t.strftime("%d/%m %H:%M"), font=f_sm, fill=MUTED)

    last_t = datetime.fromtimestamp(seg[-1][0] / 1000, VN_TZ)
    foot = (f"Nguồn {meta.get('source', 'Binance')} · nến cuối {last_t:%H:%M %d/%m/%Y} giờ VN "
            f"· O {fmt(seg[-1][1])} H {fmt(seg[-1][2])} L {fmt(seg[-1][3])} C {fmt(seg[-1][4])} "
            f"· sổ giấy, không phải khuyến nghị")
    d.text((PAD_L, H - 22), foot, font=f_sm, fill=MUTED)

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    img.save(path, "PNG", optimize=True)
    return path


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import crypto as C

    sym = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
    itv = sys.argv[2] if len(sys.argv) > 2 else "4h"
    bars = C.klines(sym, itv, 2, refresh=False)[-120:]
    entry = bars[-20][4]
    meta = {
        "symbol": sym, "interval": itv, "side": "BUY", "strategy": "vcr",
        "entry": entry, "stop0": entry * 0.95, "tp": entry * 1.10,
        "entryIdx": len(bars[-70:]) - 20,
        "exits": {"slPct": 5, "tpPct": 10, "trailPct": 7, "maxHold": 72},
    }
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "data", "cache", "chart-demo.png")
    print(render(bars, meta, out) or "không vẽ được (thiếu Pillow?)")
