#!/usr/bin/env python3
"""
Bot tín hiệu crypto: quét sàn mỗi nến, ra điểm mua, theo dõi, ra điểm bán.

Giống hệt sổ theo dõi của phần cổ phiếu, chỉ khác thị trường:

    quét N cặp thanh khoản nhất  →  chiến lược nào bắt được tín hiệu ở nến vừa đóng
    →  mở vị thế giấy ở giá hiện tại  →  mỗi lần chạy lại kiểm cắt lỗ / chốt lời /
       trailing / hết hạn giữ  →  ra ĐIỂM BÁN kèm PnL và số R

KHÔNG đặt lệnh, KHÔNG giữ khoá API sàn. Đây là sổ giấy chạy tiến về phía trước, để
đối chiếu với backtest — nếu sổ sống lệch hẳn backtest thì một trong hai đang sai.

    python scripts/crypto_bot.py --dry        # xem trước, không ghi, không gửi
    python scripts/crypto_bot.py              # chạy thật
    python scripts/crypto_bot.py --reset      # xoá sổ

Chiến lược và khối thoát lệnh lấy từ scripts/crypto.py — thêm chiến lược ở đó thì
bot này dùng được ngay.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crypto as C  # noqa: E402

try:
    import crypto_chart as CH  # noqa: E402
except Exception:  # noqa: BLE001
    CH = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
STATE = os.path.join(DATA_DIR, "crypto-ideas.json")
BACKTEST = os.path.join(DATA_DIR, "crypto-backtest.json")

VN_TZ = timezone(timedelta(hours=7))

CFG = {
    "interval": "4h",         # khung nến bot làm việc
    "pairs": 30,              # quét bao nhiêu cặp thanh khoản nhất
    "maxOpen": 8,             # tối đa bao nhiêu vị thế giấy cùng lúc
    "strategies": ["vcr", "rsi_vol_gated"],   # chạy song song, mỗi cặp chỉ một vị thế
    "lookback": 300,          # số nến tải về mỗi lần, đủ cho mọi chỉ báo
}

PER_H = 4   # số giờ mỗi nến, đặt lại theo --interval

EXIT_LABEL = {
    "stop": "chạm cắt lỗ", "trail": "cắt lỗ dời chạm", "tp": "đạt mục tiêu",
    "max_hold": "hết hạn giữ",
}


def now_vn():
    return datetime.now(VN_TZ)


def ts_vn(ms):
    return datetime.fromtimestamp(ms / 1000, VN_TZ)


def fmt(p):
    if p is None:
        return "—"
    if p >= 1000:
        return f"{p:,.0f}"
    if p >= 1:
        return f"{p:,.3f}".rstrip("0").rstrip(".")
    return f"{p:.6f}".rstrip("0")


def load(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------------------------------------------------------------------------
def fetch_recent(symbol, interval, limit):
    """Nến gần nhất. Binance chặn vùng (451) thì tự chuyển sang OKX."""
    try:
        q = urllib.parse.urlencode({"symbol": symbol, "interval": interval, "limit": limit})
        rows = C.get("/api/v3/klines?" + q)
        return [[int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])]
                for r in rows]
    except C.GeoBlocked:
        return C.okx_klines(symbol, interval, min(limit, 300))


def expectancy(strategy, interval):
    """R trung bình đã đo được của chiến lược này, để gắn vào tin nhắn."""
    bt = load(BACKTEST)
    if not bt or bt.get("interval", "1h") != interval:
        return None
    best = None
    for r in bt.get("results", []):
        if r["name"] == strategy and r.get("avgR") is not None:
            if best is None or r["avgR"] > best["avgR"]:
                best = r
    return best


# ---------------------------------------------------------------------------
def step(state, bars_by_sym, events):
    """Đẩy sổ tới nến mới nhất: thoát trước, rồi mở vị thế mới."""
    ex = C.EXIT
    per = {"1h": 1, "2h": 2, "4h": 4, "6h": 6, "12h": 12, "1d": 24}.get(CFG["interval"], 1)
    max_hold = max(3, ex["maxHold"] // per)

    still = []
    for it in state.get("open", []):
        bars = bars_by_sym.get(it["symbol"])
        if not bars:
            still.append(it)
            continue
        new = [b for b in bars if b[0] > it["lastTs"]]
        exited = False
        for b in new:
            it["held"] += 1
            it["lastTs"] = b[0]
            it["peak"] = max(it["peak"], b[2])
            if ex.get("trailPct"):
                t = it["peak"] * (1 - ex["trailPct"] / 100)
                if t > it["stop"]:
                    it["stop"] = t
                    it["trailed"] = True
            px = reason = None
            if b[3] <= it["stop"]:
                px, reason = min(b[1], it["stop"]), ("trail" if it["trailed"] else "stop")
            elif it.get("tp") and b[2] >= it["tp"]:
                px, reason = max(b[1], it["tp"]), "tp"
            elif it["held"] >= max_hold:
                px, reason = b[4], "max_hold"
            if px is None:
                continue
            close_it(it, state, events, b[0], px, reason)
            exited = True
            break
        if exited:
            continue
        last = bars[-1]
        it["lastPrice"] = last[4]
        it["pnlPct"] = round((last[4] / it["entry"] - 1) * 100, 2)
        it["r"] = round((last[4] - it["entry"]) / (it["entry"] - it["stop0"]), 2)
        still.append(it)
    state["open"] = still

    # --- tín hiệu mới ở nến vừa đóng
    held = {i["symbol"] for i in still}
    room = CFG["maxOpen"] - len(still)
    if room <= 0:
        return state
    cands = []
    for sym, bars in bars_by_sym.items():
        if sym in held or len(bars) < 80:
            continue
        x = C.Ctx(bars)
        i = len(bars) - 2          # nến vừa ĐÓNG (nến cuối còn đang chạy)
        for name in CFG["strategies"]:
            st = C.STRATEGIES.get(name)
            if not st:
                continue
            try:
                if st["fn"](x, i, st["params"]):
                    cands.append((x.volx(i), sym, name, bars))
                    break
            except Exception:  # noqa: BLE001
                continue
    cands.sort(reverse=True)

    for _, sym, name, bars in cands[:room]:
        last = bars[-1]
        entry = last[4]                       # giá hiện tại ≈ mở cửa nến đang chạy
        stop = entry * (1 - C.EXIT["slPct"] / 100)
        tp = entry * (1 + C.EXIT["tpPct"] / 100) if C.EXIT.get("tpPct") else None
        it = {
            "id": f"{sym}-{last[0]}",
            "symbol": sym, "strategy": name,
            "entryTs": last[0], "entry": entry,
            "stop": stop, "stop0": stop, "tp": tp,
            "peak": last[2], "trailed": False,
            "lastTs": last[0], "lastPrice": entry, "held": 0,
            "pnlPct": 0.0, "r": 0.0,
        }
        state["open"].append(it)
        events.append({"kind": "buy", "it": it})
    return state


def close_it(it, state, events, ts, px, reason):
    it.update(status="closed", exitTs=ts, exitPrice=px, exitReason=reason,
              pnlPct=round((px / it["entry"] - 1) * 100, 2),
              r=round((px - it["entry"]) / (it["entry"] - it["stop0"]), 2))
    state.setdefault("closed", []).insert(0, it)
    state["closed"] = state["closed"][:200]
    events.append({"kind": "sell", "it": it})


def stats_of(state):
    cl = [c for c in state.get("closed", []) if c.get("r") is not None]
    wins = [c for c in cl if c["pnlPct"] > 0]
    rs = [c["r"] for c in cl]
    return {
        "open": len(state.get("open", [])),
        "closed": len(cl),
        "winRatePct": round(len(wins) / len(cl) * 100, 1) if cl else None,
        "totalR": round(sum(rs), 2) if rs else None,
        "avgR": round(sum(rs) / len(rs), 3) if rs else None,
        "sumPnlPct": round(sum(c["pnlPct"] for c in cl), 2) if cl else None,
    }


# ---------------------------------------------------------------------------
def build_buy(it):
    ex = C.EXIT
    sym = it["symbol"].replace("USDT", "/USDT")
    return "\n".join([
        f"🟢 <b>BUY {esc(sym)}</b>",
        f"Giá: <b>{fmt(it['entry'])}</b>",
        f"Cắt lỗ {fmt(it.get('stop0') or it['stop'])}"
        + (f" · Chốt lời {fmt(it['tp'])}" if it.get("tp") else ""),
        f"Giữ tối đa {ex['maxHold']}h · {esc(it['strategy'])}",
    ])


def build_sell(it):
    sym = it["symbol"].replace("USDT", "/USDT")
    ico = "🔴" if it["pnlPct"] < 0 else "🟢"
    return "\n".join([
        f"{ico} <b>SELL {esc(sym)}</b>",
        f"Giá: <b>{fmt(it['exitPrice'])}</b> ({it['pnlPct']:+.2f}%, {it['r']:+.2f}R)",
        f"Đã giữ {it['held'] * PER_H}h · {EXIT_LABEL.get(it['exitReason'], it['exitReason'])}"
        f" · {esc(it['strategy'])}",
    ])


def build_summary(state, st):
    """Tin tổng kết ngắn, chỉ gửi khi có cờ --summary."""
    op = state.get("open", [])
    lines = [f"🪙 <b>Sổ crypto</b> · {len(op)} đang giữ"]
    for it in sorted(op, key=lambda x: -(x.get("pnlPct") or 0)):
        lines.append(f"{esc(it['symbol'].replace('USDT', ''))} {it['pnlPct']:+.2f}% "
                     f"({it['r']:+.2f}R) · cắt lỗ {fmt(it['stop'])}")
    if st["closed"]:
        lines.append(f"\n{st['closed']} lệnh đóng · thắng {st['winRatePct']}% · "
                     f"{st['avgR']:+.3f}R/lệnh")
    return "\n".join(lines)


def tg_photo(token, chat, path, caption):
    """sendPhoto bằng multipart/form-data, không cần thư viện ngoài."""
    bound = "----crypto-bot-" + os.urandom(8).hex()
    with open(path, "rb") as f:
        blob = f.read()
    parts = []
    for k, v in (("chat_id", chat), ("caption", caption), ("parse_mode", "HTML")):
        parts.append(f'--{bound}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'
                     .encode("utf-8"))
    parts.append(f'--{bound}\r\nContent-Disposition: form-data; name="photo"; '
                 f'filename="chart.png"\r\nContent-Type: image/png\r\n\r\n'.encode("utf-8"))
    parts.append(blob)
    parts.append(f"\r\n--{bound}--\r\n".encode("utf-8"))
    body = b"".join(parts)
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendPhoto", data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={bound}",
                 "Content-Length": str(len(body))})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r)


def chart_for(ev, bars_by_sym, charts_dir):
    """Vẽ ảnh chart cho một sự kiện. Thiếu Pillow hoặc lỗi thì trả None, bot vẫn gửi chữ."""
    if CH is None or not getattr(CH, "HAVE_PIL", False):
        return None
    it = ev["it"]
    bars = bars_by_sym.get(it["symbol"])
    if not bars:
        return None
    try:
        window = 70
        seg = bars[-window:]
        # vị trí nến vào lệnh trong cửa sổ đang vẽ
        ei = next((i for i, b in enumerate(seg) if b[0] >= it["entryTs"]), len(seg) - 1)
        meta = {
            "symbol": it["symbol"], "interval": CFG["interval"],
            "side": "BUY" if ev["kind"] == "buy" else "SELL",
            "strategy": it["strategy"], "entry": it["entry"],
            "stop0": it.get("stop0"), "tp": it.get("tp"), "entryIdx": ei,
            "exits": {**C.EXIT, "maxHold": C.EXIT["maxHold"]},
            "exitPrice": it.get("exitPrice"), "pnlPct": it.get("pnlPct"),
        }
        path = os.path.join(charts_dir, f"{it['symbol']}-{it['entryTs']}-{ev['kind']}.png")
        return CH.render(bars, meta, path, window=window)
    except Exception as e:  # noqa: BLE001
        print(f"  [chart] {it['symbol']}: {e}", file=sys.stderr)
        return None


def tg_send(token, chat, text):
    data = urllib.parse.urlencode({"chat_id": chat, "text": text, "parse_mode": "HTML",
                                   "disable_web_page_preview": "true"}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage",
                                 data=data, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


# ---------------------------------------------------------------------------
def send_test(symbol, args):
    """Gửi một tin mẫu kèm ảnh, dựng từ nến thật mới nhất của một mã.

    Dùng để kiểm tra token Telegram và đường gửi ảnh mà không phải chờ tín hiệu
    thật xuất hiện. Không ghi gì vào sổ.
    """
    symbol = symbol.upper()
    if not symbol.endswith("USDT"):
        symbol += "USDT"
    global PER_H
    PER_H = {"1h": 1, "2h": 2, "4h": 4, "6h": 6, "12h": 12, "1d": 24}.get(CFG["interval"], 1)
    try:
        bars = fetch_recent(symbol, CFG["interval"], CFG["lookback"])
    except Exception as e:  # noqa: BLE001
        print(f"Không lấy được nến {symbol}: {e}", file=sys.stderr)
        return 1
    if not bars:
        print(f"Không có nến cho {symbol}.", file=sys.stderr)
        return 1

    last = bars[-1]
    entry = last[4]
    it = {
        "symbol": symbol, "strategy": "gửi thử", "entryTs": last[0], "entry": entry,
        "stop": entry * (1 - C.EXIT["slPct"] / 100), "stop0": entry * (1 - C.EXIT["slPct"] / 100),
        "tp": entry * (1 + C.EXIT["tpPct"] / 100) if C.EXIT.get("tpPct") else None,
        "held": 0,
    }
    cap = "🧪 <b>GỬI THỬ</b> — không phải tín hiệu thật\n" + build_buy(it)
    img = None if args.no_chart else chart_for({"kind": "buy", "it": it},
                                               {symbol: bars},
                                               os.path.join(DATA_DIR, "cache", "charts"))
    print(f"Gửi thử {symbol} · giá {fmt(entry)} · ảnh: {img or 'không'}", file=sys.stderr)
    if args.dry:
        print(cap)
        return 0

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        print("Chưa có TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID — không gửi được.", file=sys.stderr)
        print(cap)
        return 1
    try:
        r = tg_photo(token, chat, img, cap) if img else tg_send(token, chat, cap)
        if r.get("ok"):
            print("Đã gửi Telegram." + (" (kèm ảnh)" if img else " (chỉ chữ)"), file=sys.stderr)
            return 0
        print(f"Telegram trả lỗi: {r}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"Lỗi gửi Telegram: {e}", file=sys.stderr)
        return 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--no-send", action="store_true")
    ap.add_argument("--interval", default=CFG["interval"])
    ap.add_argument("--pairs", type=int, default=CFG["pairs"])
    ap.add_argument("--summary", action="store_true", help="gửi kèm một tin tổng kết ngắn")
    ap.add_argument("--no-chart", action="store_true", help="không vẽ ảnh, chỉ gửi chữ")
    ap.add_argument("--test", nargs="?", const="BTCUSDT", metavar="MÃ",
                    help="gửi thử một tin mẫu kèm ảnh để kiểm tra đường truyền, "
                         "không động vào sổ")
    args = ap.parse_args()

    if args.reset:
        if os.path.exists(STATE):
            os.remove(STATE)
            print("Đã xoá sổ crypto.", file=sys.stderr)
        return 0

    CFG["interval"], CFG["pairs"] = args.interval, args.pairs
    if args.test:
        return send_test(args.test, args)
    global PER_H
    PER_H = {"1h": 1, "2h": 2, "4h": 4, "6h": 6, "12h": 12, "1d": 24}.get(args.interval, 1)
    state = load(STATE, {"open": [], "closed": []}) or {"open": [], "closed": []}

    try:
        universe = C.universe(CFG["pairs"])
    except Exception as e:  # noqa: BLE001
        print(f"Không lấy được danh sách cặp: {e}", file=sys.stderr)
        return 1
    need = sorted(set(universe) | {i["symbol"] for i in state.get("open", [])})
    print(f"Quét {len(need)} cặp, khung {CFG['interval']}, "
          f"chiến lược: {', '.join(CFG['strategies'])}", file=sys.stderr)

    bars_by_sym, errs = {}, 0
    for sym in need:
        try:
            bars_by_sym[sym] = fetch_recent(sym, CFG["interval"], CFG["lookback"])
        except Exception as e:  # noqa: BLE001
            errs += 1
            print(f"  [lỗi] {sym}: {str(e)[:80]}", file=sys.stderr)
    if not bars_by_sym:
        print("Không lấy được nến nào.", file=sys.stderr)
        return 1

    events = []
    state = step(state, bars_by_sym, events)
    st = stats_of(state)
    state.update(updatedAt=now_vn().strftime("%Y-%m-%d %H:%M"),
                 interval=CFG["interval"], strategies=list(CFG["strategies"]),
                 exit=dict(C.EXIT), maxOpen=CFG["maxOpen"], stats=st)

    print(f"{len(events)} sự kiện · {st['open']} đang giữ, {st['closed']} đã đóng"
          + (f", R trung bình {st['avgR']:+.3f}" if st["avgR"] is not None else "")
          + (f" · {errs} cặp lỗi" if errs else ""), file=sys.stderr)
    for e in events:
        it = e["it"]
        if e["kind"] == "buy":
            print(f"  [MUA ] {it['symbol']:<12} {fmt(it['entry'])} ({it['strategy']})", file=sys.stderr)
        else:
            print(f"  [BÁN ] {it['symbol']:<12} {fmt(it['exitPrice'])} "
                  f"{it['exitReason']} {it['pnlPct']:+.2f}% {it['r']:+.2f}R", file=sys.stderr)

    charts_dir = os.path.join(DATA_DIR, "cache", "charts")
    msgs = []
    for e in events:
        cap = build_buy(e["it"]) if e["kind"] == "buy" else build_sell(e["it"])
        img = None if args.no_chart else chart_for(e, bars_by_sym, charts_dir)
        msgs.append((cap, img))
    if args.summary:
        msgs.append((build_summary(state, st), None))
    if args.dry:
        print("\n--- Tin nhắn ---\n", file=sys.stderr)
        if not msgs:
            print("(không có tín hiệu nào)")
        for cap, img in msgs:
            print(cap)
            print(f"[ảnh: {img}]" if img else "[không có ảnh]")
            print("-" * 30)
        return 0

    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, separators=(",", ":"))
    print("Đã ghi data/crypto-ideas.json", file=sys.stderr)

    if args.no_send or not msgs:
        if not msgs:
            print("Không có tín hiệu mới nên không gửi tin.", file=sys.stderr)
        return 0
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        print("Chưa có TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID — chỉ ghi file.", file=sys.stderr)
        return 0
    sent = 0
    for cap, img in msgs:
        try:
            r = tg_photo(token, chat, img, cap) if img else tg_send(token, chat, cap)
            sent += 1 if r.get("ok") else 0
            if not r.get("ok"):
                print(f"Telegram trả lỗi: {r}", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print(f"Lỗi gửi Telegram: {e}", file=sys.stderr)
            if img:   # ảnh hỏng thì vẫn cố gửi phần chữ
                try:
                    if tg_send(token, chat, cap).get("ok"):
                        sent += 1
                except Exception:  # noqa: BLE001
                    pass
    print(f"Đã gửi {sent}/{len(msgs)} tin.", file=sys.stderr)
    return 0 if sent == len(msgs) else 1


if __name__ == "__main__":
    sys.exit(main())
