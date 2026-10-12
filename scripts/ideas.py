#!/usr/bin/env python3
"""
Tầng 2 và 3: mở "ý tưởng" khi có điểm buy, theo dõi từng phiên, ra điểm sell.

Đây là sổ theo dõi trên giấy, chạy về phía trước — không tiền thật, không lệnh thật.
Nó bám đúng luật mà backtest đã kiểm chứng, nên kết quả sống so được thẳng với
kết quả backtest; lệch nhiều là dấu hiệu bộ luật đang xuống phong độ.

Vòng đời một ý tưởng:

  phiên t:   điểm MUA xuất hiện        → ghi ý tưởng, trạng thái "chờ khớp"
  phiên t+1: khớp ở giá mở cửa          → trạng thái "đang theo dõi"
             (mở cửa cao hơn 4% so với giá tín hiệu thì bỏ, không mua đuổi)
  mỗi phiên: giá chạm cắt lỗ            → ĐIỂM SELL, lý do "chạm cắt lỗ"
             giá chạm mục tiêu          → ĐIỂM SELL, lý do "đạt mục tiêu"
             bị hạ bậc xuống GIẢM/BÁN   → ĐIỂM SELL, lý do "luật hạ bậc"
             giữ quá 40 phiên           → ĐIỂM SELL, lý do "hết thời gian"

  python scripts/ideas.py            # chạy sau fetch_ssi.py
  python scripts/ideas.py --dry      # in ra, không ghi file, không gửi
  python scripts/ideas.py --reset    # xoá sạch sổ theo dõi
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
import fetch_ssi as F  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
ANALYSIS = os.path.join(DATA_DIR, "analysis.json")
BARS_DIR = os.path.join(DATA_DIR, "bars")
IDEAS = os.path.join(DATA_DIR, "ideas.json")
BACKTEST = os.path.join(DATA_DIR, "backtest.json")

VN_TZ = timezone(timedelta(hours=7))

RULES = {
    "maxOpen": 5,          # tối đa 5 ý tưởng mở cùng lúc, như backtest
    "maxHoldDays": 40,     # chốt theo thời gian
    "maxGapEntry": 4.0,    # mở cửa cao hơn giá tín hiệu quá 4% thì bỏ, không mua đuổi
    "adjDropPct": 12.0,    # rơi hơn 12% một phiên = chuỗi giá bị điều chỉnh, không phải bị bán
    "entryRecs": ["buy"],  # chỉ mở khi khuyến nghị MUA
    "exitRecs": ["reduce", "sell"],
}

EXIT_LABEL = {
    "stop": "chạm cắt lỗ",
    "target": "đạt mục tiêu",
    "rule": "bị hạ bậc khuyến nghị",
    "time": "hết thời gian giữ",
    "gap": "bỏ vì mở cửa nhảy quá xa",
    "adjust": "giá bị điều chỉnh (cổ tức / chia tách)",
}


def n0(x):
    return "—" if x is None else f"{x:,.0f}".replace(",", ".")


def load(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def bars_for(sym, need_date):
    """Nến của một mã, ưu tiên file sẵn có; thiếu phiên mới nhất thì gọi API."""
    p = os.path.join(BARS_DIR, f"{sym}.json")
    d = load(p)
    if d and d.get("bars") and d["bars"][-1][0] >= need_date:
        return d["bars"]
    bars = F.fetch_history(sym, 120)
    if bars and bars[-1][4] < 1000:
        bars = [[b[0], b[1] * 1000, b[2] * 1000, b[3] * 1000, b[4] * 1000, b[5]] for b in bars]
    return bars


def sessions_after(bars, date):
    return [b for b in bars if b[0] > date]


# ----------------------------------------------------------------------------
def step(store, analysis, events):
    """Đẩy sổ theo dõi tới phiên mới nhất. Ghi sự kiện vào `events`."""
    data_date = analysis["dataDate"]
    by_sym = {s["symbol"]: s for s in analysis["symbols"]}
    open_ideas, closed = store.get("open", []), store.get("closed", [])

    still_open = []
    for it in open_ideas:
        sym = it["symbol"]
        try:
            bars = bars_for(sym, data_date)
        except Exception as e:  # noqa: BLE001
            print(f"[lỗi] {sym}: {e}", file=sys.stderr)
            still_open.append(it)
            continue
        if not bars:
            still_open.append(it)
            continue

        # --- 1. Ý tưởng chờ khớp: khớp ở giá mở cửa phiên kế tiếp
        if it["status"] == "pending":
            nxt = sessions_after(bars, it["signalDate"])
            if not nxt:
                still_open.append(it)
                continue
            b = nxt[0]
            gap = (b[1] / it["signalClose"] - 1) * 100
            # Biên độ một phiên là ±7% (HOSE) nên rơi hơn 12% là do chuỗi giá bị điều
            # chỉnh hồi tố, hoặc giá mở cửa đã nằm dưới cắt lỗ — cả hai làm kế hoạch
            # cũ vô nghĩa, không khớp lệnh theo nó nữa.
            if gap < -RULES["adjDropPct"] or b[1] <= it["stop"]:
                it.update(status="skipped", exitReason="adjust", exitDate=b[0],
                          exitPrice=b[1], gapPct=round(gap, 2))
                closed.insert(0, it)
                events.append({"kind": "skip", "idea": it,
                               "text": f"{sym} bỏ qua: mở cửa {n0(b[1])} lệch {gap:.1f}% so với giá "
                                       f"tín hiệu {n0(it['signalClose'])} — gần như chắc do điều chỉnh "
                                       f"cổ tức/chia tách, kế hoạch cũ không còn so được."})
                continue
            if gap > RULES["maxGapEntry"]:
                it.update(status="skipped", exitReason="gap", exitDate=b[0],
                          exitPrice=b[1], gapPct=round(gap, 2))
                closed.insert(0, it)
                events.append({"kind": "skip", "idea": it,
                               "text": f"{sym} bỏ qua: mở cửa {n0(b[1])} cao hơn giá tín hiệu "
                                       f"{gap:.1f}% — theo luật thì không mua đuổi."})
                continue
            it.update(status="open", entryDate=b[0], entryPrice=b[1],
                      lastDate=b[0], days=0, highSince=b[2])
            events.append({"kind": "buy", "idea": it,
                           "text": f"{sym} khớp mua {n0(b[1])} (mở cửa phiên {b[0][8:10]}/{b[0][5:7]})"})

        # --- 2. Đi qua từng phiên mới, kiểm tra cắt lỗ / mục tiêu
        exited = False
        for b in sessions_after(bars, it["lastDate"]):
            prev_px = it.get("lastPrice") or it.get("entryPrice") or b[4]
            it["days"] += 1
            it["lastDate"] = b[0]
            it["highSince"] = max(it.get("highSince") or b[2], b[2])
            # Điều chỉnh giá hồi tố trông y như một cú sập xuyên cắt lỗ. Đóng ý tưởng
            # với lý do rõ ràng thay vì ghi nhận một lệnh lỗ không có thật.
            if prev_px and b[1] < prev_px * (1 - RULES["adjDropPct"] / 100):
                close_idea(it, closed, events, b[0], b[1], "adjust",
                           extra=f"Mở cửa {n0(b[1])} so với {n0(prev_px)} phiên trước — "
                                 f"vượt biên độ, nên là điều chỉnh cổ tức/chia tách. "
                                 f"Số R của lệnh này không tin được.")
                exited = True
                break
            if b[3] <= it["stop"]:
                px = min(b[1], it["stop"])      # hở giá xuống dưới thì khớp xấu hơn
                close_idea(it, closed, events, b[0], px, "stop")
                exited = True
                break
            if it.get("target") and b[2] >= it["target"]:
                px = max(b[1], it["target"])
                close_idea(it, closed, events, b[0], px, "target")
                exited = True
                break
            if it["days"] >= RULES["maxHoldDays"]:
                close_idea(it, closed, events, b[0], b[4], "time")
                exited = True
                break
        if exited:
            continue

        # --- 3. Luật hạ bậc: thoát theo giá đóng cửa phiên mới nhất
        s = by_sym.get(sym)
        if s and s["recKey"] in RULES["exitRecs"] and it["status"] == "open":
            close_idea(it, closed, events, data_date, s["close"], "rule",
                       extra=f"Điểm xuống {s['score']:+d} → {s['rec']}.")
            continue

        # --- 4. Còn mở: cập nhật lãi/lỗ hiện tại
        if s:
            it["lastPrice"] = s["close"]
        elif bars:
            it["lastPrice"] = bars[-1][4]
        it["openR"] = r_of(it, it.get("lastPrice"))
        it["openPct"] = pct_of(it, it.get("lastPrice"))
        still_open.append(it)

    # --- 5. Mở ý tưởng mới từ các mã được khuyến nghị MUA
    held = {i["symbol"] for i in still_open}
    closed_today = {c["symbol"] for c in closed if c.get("exitDate") == data_date}
    room = RULES["maxOpen"] - len(still_open)
    if room > 0:
        cands = [s for s in analysis["symbols"]
                 if s["recKey"] in RULES["entryRecs"]
                 and s["symbol"] not in held and s["symbol"] not in closed_today]
        cands.sort(key=lambda s: -s["score"])
        for s in cands[:room]:
            plan = s.get("plan") or {}
            if not plan.get("stop") or plan["stop"] >= s["close"]:
                continue
            it = {
                "id": f"{s['symbol']}-{data_date}",
                "symbol": s["symbol"], "name": s.get("name", s["symbol"]),
                "status": "pending",
                "signalDate": data_date, "signalClose": s["close"],
                "score": s["score"], "rec": s["rec"],
                "stop": plan["stop"], "stop0": plan["stop"], "target": plan.get("target"),
                "rr": plan.get("rr"),
                "entryLo": plan.get("entryLo"), "entryHi": plan.get("entryHi"),
                "why": [r["text"] for r in (s.get("reasons") or [])[:2]],
                "lastDate": data_date, "days": 0,
            }
            still_open.append(it)
            events.append({"kind": "signal", "idea": it,
                           "text": f"{s['symbol']} có điểm MUA ({s['score']:+d} điểm). "
                                   f"Cắt lỗ {n0(plan['stop'])}, mục tiêu {n0(plan.get('target'))}"
                                   + (f", lời/lỗ {plan['rr']}:1." if plan.get("rr") else ".")})

    store["open"] = still_open
    store["closed"] = closed[:120]
    return store


def r_of(it, px):
    if px is None or not it.get("entryPrice"):
        return None
    risk = it["entryPrice"] - it["stop0"]
    return round((px - it["entryPrice"]) / risk, 2) if risk > 0 else None


def pct_of(it, px):
    if px is None or not it.get("entryPrice"):
        return None
    return round((px / it["entryPrice"] - 1) * 100, 2)


def close_idea(it, closed, events, date, price, reason, extra=""):
    it.update(status="closed", exitDate=date, exitPrice=price, exitReason=reason,
              exitR=r_of(it, price), exitPct=pct_of(it, price))
    closed.insert(0, it)
    r = it["exitR"]
    events.append({"kind": "sell", "idea": it,
                   "text": f"{it['symbol']} ĐIỂM SELL ở {n0(price)} — {EXIT_LABEL[reason]}"
                           + (f" ({r:+.2f}R, {it['exitPct']:+.2f}%)" if r is not None else "")
                           + (" " + extra if extra else "")})


def stats_of(store):
    closed = [c for c in store.get("closed", []) if c.get("exitR") is not None]
    wins = [c for c in closed if c["exitR"] > 0]
    rs = [c["exitR"] for c in closed]
    return {
        "open": len(store.get("open", [])),
        "closed": len(closed),
        "winRatePct": round(len(wins) / len(closed) * 100, 1) if closed else None,
        "totalR": round(sum(rs), 2) if rs else None,
        "avgR": round(sum(rs) / len(rs), 3) if rs else None,
        "skipped": len([c for c in store.get("closed", []) if c.get("exitReason") == "gap"]),
    }


# ----------------------------------------------------------------------------
def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_message(store, events, analysis, bt):
    st = stats_of(store)
    lines = [f"📋 <b>Sổ theo dõi · phiên {esc(analysis['dataDate'])}</b>",
             f"Thị trường: {esc(analysis['market'].get('regime'))}"]

    for kind, title in (("sell", "🔻 ĐIỂM SELL"), ("buy", "🟢 ĐÃ KHỚP MUA"),
                        ("signal", "⭐ ĐIỂM MUA MỚI"), ("skip", "⏭ BỎ QUA")):
        g = [e for e in events if e["kind"] == kind]
        if not g:
            continue
        lines.append(f"\n<b>{title}</b>")
        for e in g:
            lines.append(f"• {esc(e['text'])}")
            it = e["idea"]
            if kind == "signal" and it.get("why"):
                lines.append(f"  <i>{esc(' '.join(it['why'])[:200])}</i>")

    op = store.get("open", [])
    if op:
        lines.append("\n<b>👀 Đang theo dõi</b>")
        for it in op:
            if it["status"] == "pending":
                lines.append(f"• {esc(it['symbol'])} chờ khớp ở mở cửa phiên sau "
                             f"(tín hiệu {n0(it['signalClose'])})")
            else:
                r = it.get("openR")
                lines.append(f"• {esc(it['symbol'])} vào {n0(it.get('entryPrice'))} · "
                             f"nay {n0(it.get('lastPrice'))}"
                             + (f" ({r:+.2f}R, {it.get('openPct'):+.2f}%)" if r is not None else "")
                             + f" · cắt lỗ {n0(it['stop'])} · giữ {it['days']} phiên")
    else:
        lines.append("\n<b>👀 Đang theo dõi</b>\nKhông có ý tưởng nào đang mở.")

    if st["closed"]:
        lines.append(f"\n<i>Thành tích sống: {st['closed']} lệnh đã đóng, thắng {st['winRatePct']}%, "
                     f"tổng {st['totalR']:+.2f}R, trung bình {st['avgR']:+.3f}R/lệnh.</i>")
    if bt:
        v = next((x for x in bt["variants"] if x["name"] == "buy"), None)
        if v and v.get("avgR") is not None:
            lines.append(f"<i>Backtest cùng luật: {v['avgR']:+.3f}R/lệnh, thắng {v['winRatePct']}%. "
                         f"Bộ luật này không thắng được mua-và-giữ VN-Index — đây là sổ giấy để "
                         f"kiểm chứng, không phải lệnh mua.</i>")
    lines.append("\nBot không đặt lệnh.")
    return "\n".join(lines)


def tg_send(token, chat_id, text):
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text,
                                   "parse_mode": "HTML",
                                   "disable_web_page_preview": "true"}).encode()
    req = urllib.request.Request("https://api.telegram.org/bot%s/sendMessage" % token,
                                 data=data, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--no-send", action="store_true")
    args = ap.parse_args()

    if args.reset:
        if os.path.exists(IDEAS):
            os.remove(IDEAS)
            print("Đã xoá sổ theo dõi.", file=sys.stderr)
        return 0

    analysis = load(ANALYSIS)
    if not analysis:
        print("Chưa có data/analysis.json — chạy scripts/fetch_ssi.py trước.", file=sys.stderr)
        return 1

    store = load(IDEAS, {"open": [], "closed": []}) or {"open": [], "closed": []}
    if store.get("dataDate") == analysis["dataDate"]:
        print(f"Phiên {analysis['dataDate']} đã xử lý rồi.", file=sys.stderr)
        return 0

    events = []
    store = step(store, analysis, events)
    st = stats_of(store)
    store["dataDate"] = analysis["dataDate"]
    store["updatedAt"] = datetime.now(VN_TZ).strftime("%Y-%m-%d %H:%M")
    store["stats"] = st
    store["rules"] = RULES

    print(f"Phiên {analysis['dataDate']}: {len(events)} sự kiện · "
          f"{st['open']} đang mở, {st['closed']} đã đóng"
          + (f", R trung bình {st['avgR']:+.3f}" if st["avgR"] is not None else ""), file=sys.stderr)
    for e in events:
        print(f"  [{e['kind']}] {e['text']}", file=sys.stderr)

    bt = load(BACKTEST)
    msg = build_message(store, events, analysis, bt)

    if args.dry:
        print("\n--- Tin nhắn sẽ gửi ---\n", file=sys.stderr)
        print(msg)
        return 0

    with open(IDEAS, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Đã ghi data/ideas.json", file=sys.stderr)

    if args.no_send:
        return 0
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        print("Chưa có TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID — chỉ ghi file.", file=sys.stderr)
        return 0
    if not events:
        print("Không có sự kiện mới nên không gửi tin.", file=sys.stderr)
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
