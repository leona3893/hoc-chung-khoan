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
def build_message(state, events, st):
    ex = C.EXIT
    lines = [f"🪙 <b>Bot crypto · {now_vn():%H:%M %d/%m}</b> · khung {CFG['interval']}"]

    sells = [e for e in events if e["kind"] == "sell"]
    buys = [e for e in events if e["kind"] == "buy"]

    if sells:
        lines.append("\n<b>🔻 ĐIỂM BÁN</b>")
        for e in sells:
            it = e["it"]
            lines.append(f"• <b>{esc(it['symbol'])}</b> ra {fmt(it['exitPrice'])} — "
                         f"{EXIT_LABEL.get(it['exitReason'], it['exitReason'])} "
                         f"({it['pnlPct']:+.2f}%, {it['r']:+.2f}R) · giữ {it['held']} nến")
    if buys:
        lines.append("\n<b>🟢 ĐIỂM MUA</b>")
        for e in buys:
            it = e["it"]
            lines.append(f"• <b>{esc(it['symbol'])}</b> vào {fmt(it['entry'])} · "
                         f"cắt lỗ {fmt(it['stop'])} (−{ex['slPct']:.0f}%)"
                         + (f" · mục tiêu {fmt(it['tp'])} (+{ex['tpPct']:.0f}%)" if it.get("tp") else "")
                         + f" · trailing {ex['trailPct']:.0f}% · giữ tối đa {ex['maxHold']}h")
            e_ = expectancy(it["strategy"], CFG["interval"])
            tag = f" · backtest {e_['avgR']:+.3f}R/lệnh" if e_ else ""
            lines.append(f"  <i>Chiến lược {esc(it['strategy'])}{tag}</i>")

    op = state.get("open", [])
    if op:
        lines.append("\n<b>👀 Đang giữ</b>")
        for it in sorted(op, key=lambda x: -(x.get("pnlPct") or 0)):
            lines.append(f"• {esc(it['symbol'])} vào {fmt(it['entry'])} · nay {fmt(it['lastPrice'])} "
                         f"({it['pnlPct']:+.2f}%, {it['r']:+.2f}R) · cắt lỗ {fmt(it['stop'])}"
                         + (" (đã dời)" if it.get("trailed") else "")
                         + f" · {it['held']} nến")
    else:
        lines.append("\n<b>👀 Đang giữ</b>\nKhông có vị thế nào.")

    if st["closed"]:
        lines.append(f"\n<i>Thành tích sổ giấy: {st['closed']} lệnh đóng, thắng {st['winRatePct']}%, "
                     f"tổng {st['totalR']:+.2f}R, trung bình {st['avgR']:+.3f}R/lệnh.</i>")
    lines.append("<i>Sổ giấy, không đặt lệnh. Backtest 3 năm của chính các chiến lược này đều âm "
                 "và thua xa mua-giữ BTC — xem data/crypto-backtest.json.</i>")
    return "\n".join(lines)


def tg_send(token, chat, text):
    data = urllib.parse.urlencode({"chat_id": chat, "text": text, "parse_mode": "HTML",
                                   "disable_web_page_preview": "true"}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage",
                                 data=data, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--no-send", action="store_true")
    ap.add_argument("--interval", default=CFG["interval"])
    ap.add_argument("--pairs", type=int, default=CFG["pairs"])
    args = ap.parse_args()

    if args.reset:
        if os.path.exists(STATE):
            os.remove(STATE)
            print("Đã xoá sổ crypto.", file=sys.stderr)
        return 0

    CFG["interval"], CFG["pairs"] = args.interval, args.pairs
    state = load(STATE, {"open": [], "closed": []}) or {"open": [], "closed": []}

    try:
        universe = C.liquid_pairs(CFG["pairs"])
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

    msg = build_message(state, events, st)
    if args.dry:
        print("\n--- Tin nhắn ---\n", file=sys.stderr)
        print(msg)
        return 0

    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, separators=(",", ":"))
    print("Đã ghi data/crypto-ideas.json", file=sys.stderr)

    if args.no_send or not events:
        if not events:
            print("Không có sự kiện mới nên không gửi tin.", file=sys.stderr)
        return 0
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        print("Chưa có TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID — chỉ ghi file.", file=sys.stderr)
        return 0
    try:
        r = tg_send(token, chat, msg)
        print("Đã gửi Telegram." if r.get("ok") else f"Telegram trả lỗi: {r}", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"Lỗi gửi Telegram: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
