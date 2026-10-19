#!/usr/bin/env python3
"""
Bot theo xu hướng: luật tính trên NẾN NGÀY, nhưng chạy mỗi giờ để canh.

Khác bot crypto_bot.py ở chỗ căn bản:

    crypto_bot.py   bắt đáy, nến 1h, ~1.300 lệnh/3 năm, backtest ÂM
    trend_bot.py    theo xu hướng, nến NGÀY, ~46-82 lệnh/8 năm, backtest DƯƠNG

Vì sao luật phải tính trên nến ngày: cùng chiến lược này áp lên nến 1h cho
−57% (ma200) và −37% (donchian), trong khi trên nến ngày cho +1.353% và
+1.405%. Chênh lệch đến từ số lệnh: 873 so với 46. Phí ăn hết.

Vậy "chạy mỗi giờ" ở đây nghĩa là gì:

    • Quyết định vào/ra CHỈ xảy ra khi một nến ngày vừa đóng (07:00 giờ VN).
      Nến ngày chưa đóng thì mọi chỉ báo còn thay đổi, quyết theo nó là tự lừa mình.
    • Những giờ còn lại bot vẫn chạy, nhưng chỉ để CANH: báo khi giá đã xuyên
      xuống dưới ngưỡng thoát ngay trong ngày, để bạn biết trước thay vì đợi
      tới sáng hôm sau. Đó là cảnh báo, không phải lệnh — sổ chỉ đổi lúc nến đóng.

    python scripts/trend_bot.py --dry          # xem trước
    python scripts/trend_bot.py                # chạy thật
    python scripts/trend_bot.py --test BTC     # gửi thử một tin kèm ảnh
    python scripts/trend_bot.py --reset        # xoá sổ

Đặt lệnh thật: bật LIVE_TRADING=testnet|live, xem scripts/exchange.py. Sổ giấy vẫn là
nơi ra quyết định, exchange.py chỉ làm theo — và bạn chốt tay được mà không làm rối bot.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crypto as C  # noqa: E402
import crypto_bot as B  # noqa: E402  (dùng lại phần gửi Telegram và vẽ ảnh)
import exchange as X  # noqa: E402  (đặt lệnh thật — chỉ chạy khi LIVE_TRADING bật)

try:
    import crypto_chart as CH  # noqa: E402
except Exception:  # noqa: BLE001
    CH = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
# Trên VPS nên trỏ sổ ra ngoài repo (TREND_STATE) để `git pull` không đụng file
# mà GitHub Actions cũng đang commit.
STATE = os.environ.get("TREND_STATE") or os.path.join(DATA_DIR, "trend-ideas.json")

VN_TZ = timezone(timedelta(hours=7))

CFG = {
    "interval": "1d",                 # luật tính trên nến ngày — không đổi thành 1h
    # 10 coin lớn. Walk-forward + bootstrap trên rổ này: donchian_btc có xác suất
    # dương 100%, và năm 2022 sập không mất đồng nào nhờ lọc BTC.
    "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
                "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "LTCUSDT"],
    "strategy": "donchian_btc",       # hoặc donchian / momentum / ma200 / golden
    "maxOpen": 5,
    "capital": 150,                   # vốn thật dự định bỏ vào (USDT) — chia đều 5 phần
    "lookback": 400,                  # đủ cho MA200 ngày
    "warnNear": 3.0,                  # còn cách ngưỡng thoát dưới 3% thì nhắc
}

LABEL = {"donchian_btc": "phá đỉnh 20 ngày khi BTC trên MA200, ra khi thủng đáy 10 ngày",
         "momentum": "giá vượt giá 90 ngày trước, ra khi thủng lại",
         "donchian": "phá đỉnh 20 ngày, ra khi thủng đáy 10 ngày",
         "ma200": "vượt MA200, ra khi mất MA200",
         "ma100": "vượt MA100, ra khi mất MA100",
         "golden": "MA50 cắt lên MA200, ra khi cắt xuống"}


def chat_id():
    """Mặc định gửi chung chat với bot bắt đáy. Muốn tách riêng thì thêm secret
    TELEGRAM_CHAT_ID_TREND — vẫn dùng chung token, chỉ khác chat."""
    return (os.environ.get("TELEGRAM_CHAT_ID_TREND", "").strip()
            or os.environ.get("TELEGRAM_CHAT_ID", "").strip())


def now_vn():
    return datetime.now(VN_TZ)


def load(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def exit_level(x, i, strat_name, params):
    """Ngưỡng giá mà nếu thủng thì luật bảo thoát — để canh trong ngày."""
    if strat_name in ("donchian", "donchian_btc"):
        n = params.get("out", 10)
        return min(x.l[max(0, i - n):i]) if i >= n else None
    if strat_name == "momentum":
        n = params.get("look", 90)
        return x.c[i - n] if i >= n else None
    if strat_name in ("ma200", "ma100"):
        return (x.sma200 if strat_name == "ma200" else x.sma100)[i]
    if strat_name == "golden":
        return x.sma200[i]
    return None


# ---------------------------------------------------------------------------
def step(state, data, events):
    """Chỉ gọi khi có nến ngày mới. data: {sym: (bars, Ctx)}"""
    strat = C.STRATEGIES[CFG["strategy"]]
    fn, exit_fn, params = strat["fn"], strat.get("exitFn"), strat["params"]
    still = []

    for it in state.get("open", []):
        sym = it["symbol"]
        if sym not in data:
            still.append(it)
            continue
        bars, x = data[sym]
        i = len(bars) - 2          # nến ngày vừa ĐÓNG
        if bars[i][0] <= it["lastTs"]:
            still.append(it)
            continue
        it["lastTs"] = bars[i][0]
        it["days"] += 1
        it["lastPrice"] = bars[i][4]
        it["pnlPct"] = round((bars[i][4] / it["entry"] - 1) * 100, 2)
        if exit_fn and exit_fn(x, i, params):
            it.update(status="closed", exitTs=bars[i][0], exitPrice=bars[i][4],
                      exitReason="rule")
            state.setdefault("closed", []).insert(0, it)
            # Giữ toàn bộ lịch sử: trang so-lenh.html cần đủ mọi lệnh để tính thành tích.
            events.append({"kind": "sell", "it": it})
            continue
        still.append(it)

    state["open"] = still
    held = {i["symbol"] for i in still}
    room = CFG["maxOpen"] - len(still)
    for sym in CFG["symbols"]:
        if room <= 0:
            break
        if sym in held or sym not in data:
            continue
        bars, x = data[sym]
        i = len(bars) - 2
        if i < 210:
            continue
        try:
            if not fn(x, i, params):
                continue
        except Exception:  # noqa: BLE001
            continue
        entry = bars[-1][4]        # khớp ở giá hiện tại, tức mở cửa nến ngày mới
        it = {
            "symbol": sym, "strategy": CFG["strategy"], "entryTs": bars[-1][0],
            "entry": entry, "lastTs": bars[i][0], "lastPrice": entry,
            "days": 0, "pnlPct": 0.0, "status": "open",
            "exitLevel": exit_level(x, i, CFG["strategy"], params),
        }
        still.append(it)
        room -= 1
        events.append({"kind": "buy", "it": it})
    state["open"] = still
    return state


def stats_of(state):
    cl = state.get("closed", [])
    wins = [c for c in cl if (c.get("pnlPct") or 0) > 0]
    return {
        "open": len(state.get("open", [])),
        "closed": len(cl),
        "winRatePct": round(len(wins) / len(cl) * 100, 1) if cl else None,
        "sumPnlPct": round(sum(c.get("pnlPct") or 0 for c in cl), 2) if cl else None,
    }


# ---------------------------------------------------------------------------
def size_line(it):
    """Gợi ý số tiền cho mỗi lệnh: chia đều vốn cho số vị thế tối đa."""
    usdt = CFG["capital"] / CFG["maxOpen"]
    qty = usdt / it["entry"]
    lines = [f"Mua: <b>~{usdt:.0f} USDT</b> (≈ {qty:.6g} {it['symbol'].replace('USDT', '')})"]
    if it.get("exitLevel") and it["exitLevel"] < it["entry"]:
        loss = usdt * (1 - it["exitLevel"] / it["entry"])
        lines.append(f"Nếu thủng ngưỡng: lỗ ~{loss:.1f} USDT "
                     f"(−{(1 - it['exitLevel'] / it['entry']) * 100:.1f}%)")
    return lines


def build_buy(it):
    return "\n".join([
        f"🟢 <b>BUY {B.esc(it['symbol'].replace('USDT', '/USDT'))}</b> · 📈1D",
        f"Giá: <b>{B.fmt(it['entry'])}</b>",
        *size_line(it),
        f"Ra khi thủng {B.fmt(it['exitLevel'])}" if it.get("exitLevel") else "Ra theo luật",
        f"Khung ngày · {LABEL.get(it['strategy'], it['strategy'])}",
    ])


def build_sell(it):
    return "\n".join([
        f"🔴 <b>SELL {B.esc(it['symbol'].replace('USDT', '/USDT'))}</b> · 📈1D",
        f"Giá: <b>{B.fmt(it['exitPrice'])}</b> ({it['pnlPct']:+.2f}%)",
        f"Đã giữ {it['days']} ngày · xu hướng gãy",
    ])


def build_hold(it):
    """Nến ngày đóng mà lệnh vẫn sống: báo lãi/lỗ và ngưỡng thoát MỚI.

    Với donchian, ngưỡng thoát là đáy 10 ngày — giá leo thì ngưỡng cũng leo theo,
    nên tin này cho biết phần lãi đã được khoá tới đâu.
    """
    return "\n".join([
        f"📊 <b>Đang giữ {B.esc(it['symbol'].replace('USDT', '/USDT'))}</b> · 📈1D",
        f"Giá: <b>{B.fmt(it['lastPrice'])}</b> ({it['pnlPct']:+.2f}%) · vào {B.fmt(it['entry'])}",
        f"Ngưỡng thoát nay: <b>{B.fmt(it.get('exitLevel'))}</b>"
        + (f" (dưới giá {abs((it['lastPrice'] / it['exitLevel'] - 1) * 100):.1f}%)"
           if it.get("exitLevel") else ""),
        f"Đã giữ {it['days']} ngày · xu hướng còn nguyên",
    ])


def build_warn(it, px, lvl):
    return "\n".join([
        f"⚠️ <b>{B.esc(it['symbol'].replace('USDT', '/USDT'))} đang thủng ngưỡng thoát</b> · 📈1D",
        f"Giá {B.fmt(px)} · ngưỡng {B.fmt(lvl)}",
        f"Luật chỉ chốt theo nến ngày, nên sổ chưa đóng lệnh. "
        f"Nếu nến hôm nay đóng dưới mức này thì sáng mai có tin SELL.",
    ])


def chart(it, bars, kind):
    if CH is None or not getattr(CH, "HAVE_PIL", False):
        return None
    seg = bars[-70:]
    ei = next((i for i, b in enumerate(seg) if b[0] >= it["entryTs"]), len(seg) - 1)
    meta = {
        "symbol": it["symbol"], "interval": "1d",
        "side": "BUY" if kind == "buy" else "SELL",
        "strategy": it["strategy"], "entry": it["entry"],
        "stop0": it.get("exitLevel"), "tp": None, "entryIdx": ei,
        "exits": {"slPct": 0, "tpPct": None, "trailPct": None, "maxHold": 0},
        "exitPrice": it.get("exitPrice"), "pnlPct": it.get("pnlPct"),
    }
    try:
        return CH.render(bars, meta, os.path.join(DATA_DIR, "cache", "charts",
                                                  f"trend-{it['symbol']}-{it['entryTs']}-{kind}.png"))
    except Exception as e:  # noqa: BLE001
        print(f"  [chart] {it['symbol']}: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--no-send", action="store_true")
    ap.add_argument("--strategy", default=CFG["strategy"], choices=list(LABEL))
    ap.add_argument("--symbols", default=",".join(CFG["symbols"]))
    ap.add_argument("--test", nargs="?", const="BTCUSDT", metavar="MÃ")
    args = ap.parse_args()

    if args.reset:
        if os.path.exists(STATE):
            os.remove(STATE)
            print("Đã xoá sổ xu hướng.", file=sys.stderr)
        return 0

    CFG["strategy"] = args.strategy
    CFG["symbols"] = [s.strip().upper() + ("" if s.strip().upper().endswith("USDT") else "USDT")
                      for s in args.symbols.split(",") if s.strip()]

    data = {}
    need = list(CFG["symbols"]) + ([] if "BTCUSDT" in CFG["symbols"] else ["BTCUSDT"])
    for sym in need:
        try:
            bars = B.fetch_recent(sym, CFG["interval"], CFG["lookback"])
            if len(bars) >= 220:
                data[sym] = (bars, C.Ctx(bars))
        except Exception as e:  # noqa: BLE001
            print(f"  [lỗi] {sym}: {str(e)[:80]}", file=sys.stderr)

    # Chế độ thị trường theo BTC cho chiến lược có lọc (donchian_btc)
    if "BTCUSDT" in data:
        bb, bx = data["BTCUSDT"]
        C.REGIME.clear()
        C.REGIME.update({bb[k][0]: ("tăng" if (bx.sma200[k] and bb[k][4] > bx.sma200[k]) else "giảm")
                         for k in range(len(bb))})
        k = len(bb) - 2
        print(f"BTC {'TRÊN' if C.REGIME[bb[k][0]] == 'tăng' else 'DƯỚI'} MA200 ngày "
              f"({B.fmt(bb[k][4])} so với {B.fmt(bx.sma200[k])})", file=sys.stderr)
    if "BTCUSDT" not in CFG["symbols"]:
        data.pop("BTCUSDT", None)
    if not data:
        print("Không lấy được nến ngày.", file=sys.stderr)
        return 1

    if args.test:
        sym = args.test.upper()
        if not sym.endswith("USDT"):
            sym += "USDT"
        if sym not in data:
            bars = B.fetch_recent(sym, CFG["interval"], CFG["lookback"])
            data[sym] = (bars, C.Ctx(bars))
        bars, x = data[sym]
        i = len(bars) - 2
        it = {"symbol": sym, "strategy": CFG["strategy"], "entryTs": bars[-1][0],
              "entry": bars[-1][4], "exitLevel": exit_level(x, i, CFG["strategy"],
                                                            C.STRATEGIES[CFG["strategy"]]["params"])}
        cap = "🧪 <b>GỬI THỬ</b> — không phải tín hiệu thật\n" + build_buy(it)
        img = chart(it, bars, "buy")
        print(f"Gửi thử {sym} · {B.fmt(it['entry'])} · ảnh {'có' if img else 'không'}", file=sys.stderr)
        if args.dry:
            print(cap)
            return 0
        tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(), chat_id()
        if not tok or not chat:
            print("Chưa có token Telegram.", file=sys.stderr)
            print(cap)
            return 1
        r = B.tg_photo(tok, chat, img, cap) if img else B.tg_send(tok, chat, cap)
        print("Đã gửi." if r.get("ok") else f"Lỗi: {r}", file=sys.stderr)
        return 0 if r.get("ok") else 1

    state = load(STATE, {"open": [], "closed": []}) or {"open": [], "closed": []}
    events, msgs = [], []

    # --- nến ngày mới đóng chưa?
    # mốc của nến ngày vừa đóng — nến cuối cùng trong mảng vẫn đang chạy
    newest_closed = max(bars[-2][0] for bars, _ in data.values())
    if state.get("lastDaily") != newest_closed:
        state = step(state, data, events)
        state["lastDaily"] = newest_closed
        for e in events:
            bars = data[e["it"]["symbol"]][0]
            msgs.append((build_buy(e["it"]) if e["kind"] == "buy" else build_sell(e["it"]),
                         chart(e["it"], bars, e["kind"])))
        print(f"Nến ngày mới: {len(events)} sự kiện.", file=sys.stderr)
        daily_close = True
    else:
        daily_close = False
        print("Chưa có nến ngày mới — chỉ canh ngưỡng.", file=sys.stderr)

    # --- canh trong ngày: giá đã thủng ngưỡng thoát chưa
    warned = set(state.get("warned") or [])
    for it in state.get("open", []):
        sym = it["symbol"]
        if sym not in data:
            continue
        bars, x = data[sym]
        px = bars[-1][4]
        lvl = exit_level(x, len(bars) - 2, it["strategy"],
                         C.STRATEGIES[it["strategy"]]["params"])
        it["exitLevel"], it["lastPrice"] = lvl, px
        it["pnlPct"] = round((px / it["entry"] - 1) * 100, 2)
        key = f"{sym}-{bars[-1][0]}"
        if lvl and px < lvl and key not in warned:
            msgs.append((build_warn(it, px, lvl), None))
            warned.add(key)
        elif daily_close and not any(e["it"]["symbol"] == sym for e in events):
            # Nến ngày đóng, lệnh vẫn sống: báo lãi/lỗ và ngưỡng thoát mới.
            # Đây là câu trả lời cho "giá vẫn leo thì sao" — không bán, chỉ nâng ngưỡng.
            msgs.append((build_hold(it), None))
    state["warned"] = sorted(warned)[-20:]

    # --- đặt lệnh thật theo sổ giấy (mặc định tắt)
    if X.enabled():
        try:
            live = X.sync(state, {s: d[0][-1][0] for s, d in data.items()},
                          {s: d[0][-1][4] for s, d in data.items()},
                          CFG["capital"], CFG["maxOpen"], dry=args.dry)
            msgs += [(m, None) for m in live]
        except Exception as e:  # noqa: BLE001
            print(f"  [sàn] LỖI: {e}", file=sys.stderr)
            msgs.append((f"❗ <b>Lỗi đặt lệnh</b>: {B.esc(str(e)[:300])}", None))

    st = stats_of(state)
    state.update(updatedAt=now_vn().strftime("%Y-%m-%d %H:%M"), strategy=CFG["strategy"],
                 symbols=CFG["symbols"], interval=CFG["interval"], stats=st)
    for it in state.get("open", []):
        print(f"  giữ {it['symbol']:<10} vào {B.fmt(it['entry'])} · nay {B.fmt(it['lastPrice'])}"
              f" ({it['pnlPct']:+.2f}%) · ngưỡng thoát {B.fmt(it.get('exitLevel'))}", file=sys.stderr)

    if args.dry:
        for cap, img in msgs:
            print(cap)
            print(f"[ảnh: {img}]" if img else "[không ảnh]")
            print("-" * 30)
        if not msgs:
            print("(không có tin nào)")
        return 0

    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, separators=(",", ":"))
    flag = os.path.join(DATA_DIR, "cache", "trend-events.flag")
    os.makedirs(os.path.dirname(flag), exist_ok=True)
    if events:
        with open(flag, "w", encoding="utf-8") as f:
            f.write(str(len(events)))
    elif os.path.exists(flag):
        os.remove(flag)

    if args.no_send or not msgs:
        return 0
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(), chat_id()
    if not tok or not chat:
        print("Chưa có token Telegram — chỉ ghi sổ.", file=sys.stderr)
        return 0
    sent = 0
    for cap, img in msgs:
        try:
            r = B.tg_photo(tok, chat, img, cap) if img else B.tg_send(tok, chat, cap)
            sent += 1 if r.get("ok") else 0
        except Exception as e:  # noqa: BLE001
            print(f"Lỗi gửi: {e}", file=sys.stderr)
    print(f"Đã gửi {sent}/{len(msgs)} tin.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
