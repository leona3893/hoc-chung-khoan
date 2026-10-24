#!/usr/bin/env python3
"""
Đặt lệnh thật (hoặc testnet) cho bot bắt đáy nến 1h — cách B: lệnh bảo vệ nằm sẵn trên sàn.

Sổ GIẤY của crypto_bot.py ra quyết định, file này làm theo:

    sổ giấy mở lệnh trong giờ này   →  mua market, rồi đặt ngay OCO trên sàn:
                                        chốt lời (LIMIT_MAKER) + cắt lỗ (STOP_LOSS market)
    sổ giấy dời cắt lỗ (trailing)   →  huỷ OCO cũ, đặt OCO mới với cắt lỗ cao hơn
    sàn khớp OCO giữa hai lần chạy  →  ghi lời/lỗ theo giá khớp thật
    sổ giấy đóng lệnh vì lý do khác →  huỷ OCO, bán market
      (về trung bình 24h, hết hạn giữ)

Mức chốt lời/cắt lỗ thật = mức của sổ giấy × (giá khớp thật / giá vào sổ giấy). Nhờ vậy
lệnh thật đi đúng % như sổ giấy dù giá khớp lệch chút (và chạy được cả trên testnet,
nơi giá lệch hẳn giá thật).

BẠN GIÀNH QUYỀN MỘT LỆNH bằng cách HUỶ OCO của nó trên app. Lần chạy sau bot thấy OCO
bị huỷ mà không phải do nó, thì nhường hẳn lệnh đó cho bạn: không đặt lại OCO, không
bán theo luật nữa. Khi bạn bán, bot tìm lệnh bán của bạn và ghi lời/lỗ.

    LIVE_TRADING=testnet|live, BINANCE_API_KEY, BINANCE_API_SECRET   (như exchange.py)
    LIVE_DIP_STATE=đường/dẫn/live-dip.json   (tuỳ chọn, mặc định data/cache/live-dip.json)

    python scripts/live_dip.py status
    python scripts/live_dip.py panic --yes          # huỷ OCO và bán hết coin bot giữ
    python scripts/live_dip.py test ENA             # testnet: bot mua + đặt OCO
    python scripts/live_dip.py test ENA --trail     # testnet: sổ giấy dời cắt lỗ → bot thay OCO
    python scripts/live_dip.py test ENA --manual    # testnet: giả làm bạn huỷ OCO rồi bán
    python scripts/live_dip.py test ENA --rule      # testnet: sổ giấy đóng lệnh → bot bán
"""

import argparse
import hashlib
import json
import os
import sys
import time
from decimal import ROUND_DOWN, Decimal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import exchange as X  # noqa: E402
import crypto as C  # noqa: E402  (khối thoát lệnh dùng chung với sổ giấy: trailing, giữ tối đa)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "cache")
LEDGER = os.environ.get("LIVE_DIP_STATE") or os.path.join(CACHE, "live-dip.json")

X.EXIT_LABEL.update({
    "stop": "chạm cắt lỗ", "trail": "cắt lỗ dời chạm", "tp": "đạt chốt lời",
    "strategy": "giá hồi về trung bình 24h", "max_hold": "hết hạn giữ",
})
MOVE_MIN = 0.002      # cắt lỗ phải dời lên ít nhất 0,2% mới thay OCO, tránh huỷ/đặt vô ích


def short(pid):
    """Mã lệnh của Binance tối đa 36 ký tự — rút id lệnh giấy thành 12 ký tự cố định."""
    return "dp" + hashlib.md5(pid.encode()).hexdigest()[:12]


def price_str(p, tick):
    q = (Decimal(str(p)) / tick).to_integral_value(rounding=ROUND_DOWN) * tick
    return format(q.normalize(), "f")


# ---------------------------------------------------------------------------
def place_protect(c, pos, f, stop, tp):
    """Đặt OCO (hoặc chỉ cắt lỗ nếu không có chốt lời).

    Trả về None nếu đặt được; "stop"/"tp" nếu giá hiện tại đã vượt mức đó —
    bên gọi phải bán market ngay, đúng như sổ giấy sẽ làm.
    """
    sym = pos["symbol"]
    qty = X.floor_qty(pos["qty"], f["step"])
    ver = pos.get("ver", 0) + 1
    cid = f"{short(pos['key'])}P{ver}"
    try:
        if tp:
            r = c.oco(sym, qty, price_str(tp, f["tick"]), price_str(stop, f["tick"]), cid)
            ids = [o["orderId"] for o in r["orders"]]
            pos["protect"] = {"list": r["orderListId"], "orders": ids}
        else:
            r = c.stop_order(sym, qty, price_str(stop, f["tick"]), cid)
            ids = [r["orderId"]]
            pos["protect"] = {"order": r["orderId"], "orders": ids}
    except X.ApiError:
        cur = c.price(sym)
        if cur <= stop:
            return "stop"
        if tp and cur >= tp:
            return "tp"
        raise
    pos["ver"] = ver
    pos["liveStop"], pos["liveTp"] = stop, tp
    pos.setdefault("botOrderIds", []).extend(ids)
    return None


def protect_status(c, pos):
    """("active" | "filled" | "canceled" | "expired", [lệnh đã khớp])

    canceled = có người huỷ (CANCELED) — bạn, hoặc chính bot lúc thay OCO.
    expired  = sàn cho hết hạn mà không khớp: cắt lỗ đã kích hoạt nhưng lệnh market
               không có người mua (sổ lệnh mỏng — hay gặp trên testnet). KHÔNG phải bạn huỷ.
    """
    p = pos["protect"]
    if "list" in p:
        if c.order_list(p["list"])["listOrderStatus"] != "ALL_DONE":
            return "active", []
    filled, statuses = [], []
    for oid in p["orders"]:
        o = c.order(pos["symbol"], oid)
        if o["status"] in ("NEW", "PARTIALLY_FILLED") and "list" not in p:
            return "active", []
        statuses.append(o["status"])
        if float(o["executedQty"]) > 0:
            filled.append(o)
    if filled:
        return "filled", filled
    return ("canceled", []) if "CANCELED" in statuses else ("expired", [])


def cancel_protect(c, pos):
    p = pos.get("protect")
    if not p:
        return
    try:
        if "list" in p:
            c.cancel_list(pos["symbol"], p["list"])
        else:
            c.cancel_order(pos["symbol"], p["order"])
    except X.ApiError as e:
        if e.code != -2011:      # -2011: lệnh không còn (vừa khớp hoặc đã huỷ)
            raise
    pos["protect"] = None


def sell_market(c, led, pos, reason, msgs, tag):
    f = c.filters(pos["symbol"])
    free = c.balances().get(f["base"], (0.0, 0.0))[0]
    qty = X.floor_qty(min(pos["qty"], free), f["step"])
    px = c.price(pos["symbol"])
    if float(qty) * px < f["minNotional"]:
        X.close_pos(led, pos, "dust", float(qty) or pos["qty"], (float(qty) or pos["qty"]) * px, msgs, tag)
        return
    o = c.market(pos["symbol"], "SELL", f"{short(pos['key'])}S{pos.get('sellTry', 0)}", qty=qty)
    if float(o.get("executedQty") or 0) <= 0:
        # Không ai mua (sổ lệnh mỏng). Giữ lệnh trong sổ, lần chạy sau thử bán lại.
        # Mã lệnh bán đổi theo số lần thử, vì sàn không nhận lại mã của lệnh vừa hết hạn.
        pos["sellTry"] = pos.get("sellTry", 0) + 1
        if pos["sellTry"] == 1:
            msgs.append(f"⚠️ Bán {X.pair(pos['symbol'])} ({X.EXIT_LABEL.get(reason, reason)}) "
                        f"không khớp — sổ lệnh{' testnet' if c.mode == 'testnet' else ''} không có "
                        f"người mua. Bot giữ lệnh và thử bán lại mỗi giờ.{tag}")
        return False
    q, quote = X.fill_of(c, pos["symbol"], o, f["base"])
    X.close_pos(led, pos, reason, q, quote, msgs, tag)
    return True


def filled_reason(pos, orders):
    if any(o["type"] in ("LIMIT_MAKER", "LIMIT") for o in orders):
        return "tp"
    return "trail" if pos.get("trailed") else "stop"


# ---------------------------------------------------------------------------
def sync(paper, bar_open, capital, slots, client=None, dry=False, path=None):
    """Đưa tài khoản về khớp sổ giấy của crypto_bot. Trả về danh sách tin nhắn.

    paper     sổ giấy (dict "open"/"closed", mỗi lệnh có id, symbol, strategy, entry,
              entryTs, stop, tp, trailed)
    bar_open  {symbol: mốc mở nến đang chạy} — chỉ mua lệnh giấy mở trong GIỜ NÀY
    slots     {chiến lược: số suất} — vốn chia đều cho tổng số suất
    """
    path = path or LEDGER
    c = client or X.Binance()
    tag = " · 🧪testnet" if c.mode == "testnet" else ""
    msgs = []

    def log(s):
        print(f"  [sàn] {s}", file=sys.stderr)

    if c.mode == "live" and not dry:
        X.guard(c, log)

    led = X.load_ledger(path)
    led["mode"] = c.mode
    popen = {it["id"]: it for it in paper.get("open", [])}
    pclosed = {it["id"]: it for it in paper.get("closed", [])[:500]}

    # 1) Lệnh bot đang quản lý: OCO khớp chưa, bạn có huỷ không, sổ giấy bảo gì.
    still, cur = [], list(led["open"])
    for i, pos in enumerate(cur):
        if pos["status"] == "user":
            still.append(pos)
            continue
        sym, f = pos["symbol"], c.filters(pos["symbol"])

        if pos.get("protect"):
            st, filled = protect_status(c, pos)
            if st == "filled":
                q = quote = 0.0
                for o in filled:
                    a, b = X.fill_of(c, sym, o, f["base"])
                    q, quote = q + a, quote + b
                reason = filled_reason(pos, filled)
                log(f"{sym}: sàn đã khớp {reason}")
                if not dry:
                    X.close_pos(led, pos, reason, q, quote, msgs, tag)
                else:
                    still.append(pos)
                continue
            if st == "expired":
                # Cắt lỗ đã chạm và kích hoạt, nhưng lệnh market không khớp. Bán lại ngay.
                reason = "trail" if pos.get("trailed") else "stop"
                log(f"{sym}: cắt lỗ kích hoạt nhưng không khớp → bán market lại")
                if dry:
                    still.append(pos)
                    continue
                pos["protect"] = None
                if not sell_market(c, led, pos, reason, msgs, tag):
                    still.append(pos)
                continue
            if st == "canceled":
                if pos.get("replacing"):
                    pos["protect"] = None            # bot huỷ dở lần trước, đặt lại bên dưới
                else:
                    log(f"{sym}: OCO bị huỷ không phải do bot → nhường cho bạn")
                    if not dry:
                        pos["status"] = "user"
                        msgs.append("\n".join([
                            f"🙋 <b>Bạn đã huỷ OCO {X.pair(sym)}</b>{tag}",
                            "Bot nhường lệnh này cho bạn: không đặt lại OCO, không bán theo luật.",
                            "Khi bạn bán, bot sẽ ghi lời/lỗ.",
                        ]))
                    still.append(pos)
                    continue

        # Sổ giấy đã đóng lệnh này (về trung bình, hết hạn, hoặc chạm mức mà sàn chưa khớp)
        if pos["key"] not in popen:
            if pos["key"] not in pclosed:
                log(f"{sym}: sổ giấy không còn lệnh này — giữ nguyên, OCO vẫn bảo vệ")
                if not pos.get("orphanWarned") and not dry:
                    pos["orphanWarned"] = True
                    msgs.append(f"⚠️ <b>{X.pair(sym)}</b>: sổ giấy không còn lệnh này. Bot để nguyên "
                                f"OCO. Muốn đóng thì huỷ OCO rồi bán tay, hoặc dùng panic.{tag}")
                still.append(pos)
                continue
            reason = pclosed[pos["key"]].get("exitReason") or "strategy"
            log(f"{sym}: sổ giấy đóng ({reason}) → huỷ OCO, bán market")
            if dry:
                still.append(pos)
                continue
            cancel_protect(c, pos)
            if not sell_market(c, led, pos, reason, msgs, tag):
                still.append(pos)
            continue

        # Sổ giấy còn giữ: đặt OCO nếu chưa có, hoặc thay khi cắt lỗ đã dời lên.
        it = popen[pos["key"]]
        stop = it["stop"] * pos["k"]
        tp = it["tp"] * pos["k"] if it.get("tp") else None
        need = not pos.get("protect") or stop > pos["liveStop"] * (1 + MOVE_MIN)
        if need:
            log(f"{sym}: {'đặt' if not pos.get('protect') else 'dời'} cắt lỗ → {X.num(stop)}")
            if dry:
                still.append(pos)
                continue
            if pos.get("protect"):
                # Ghi cờ TRƯỚC khi huỷ: lỡ chết giữa huỷ và đặt, lần sau bot biết OCO
                # trống là do chính nó, không nhầm thành bạn giành quyền.
                pos["replacing"] = True
                X.save_ledger(dict(led, open=still + cur[i:]), path)
                cancel_protect(c, pos)
            pos["trailed"] = bool(it.get("trailed"))
            try:
                hit = place_protect(c, pos, f, stop, tp)
            except X.ApiError as e:
                msgs.append(f"⚠️ {X.pair(sym)}: chưa đặt được OCO ({e}). Giờ sau bot thử lại.{tag}")
                still.append(pos)
                continue
            pos.pop("replacing", None)
            if hit:
                log(f"{sym}: giá đã vượt mức {hit} → bán market")
                if not sell_market(c, led, pos, hit if hit == "tp" else ("trail" if pos["trailed"] else "stop"),
                                   msgs, tag):
                    still.append(pos)
                continue
        still.append(pos)
    led["open"] = still

    # 2) Lệnh đã nhường cho bạn: bạn bán chưa?
    #    Dấu hiệu chính là LỆNH BÁN không phải của bot kể từ lúc mua. Không dựa vào số dư,
    #    vì bạn có thể có sẵn coin đó (testnet thì có sẵn mọi coin) — bán xong số dư vẫn
    #    dư, nhìn số dư sẽ tưởng chưa bán. Số dư hụt mà không thấy lệnh bán nào thì là
    #    coin bị chuyển đi / dùng Convert / testnet reset.
    bal = c.balances()
    seen = led.setdefault("seenSell", {})       # mốc lệnh bán đã tính, để không tính hai lần
    for sym in sorted({p["symbol"] for p in led["open"] if p["status"] == "user"}):
        f = c.filters(sym)
        step = float(f["step"])
        users = sorted([p for p in led["open"] if p["symbol"] == sym and p["status"] == "user"],
                       key=lambda p: p["entryMs"])
        mine = {i for p in led["open"] + led["closed"][:50] if p["symbol"] == sym
                for i in p.get("botOrderIds", [])}
        since = max(min(p["entryMs"] for p in users), seen.get(sym, 0) + 1)
        sells = sorted([t for t in c.trades(sym, start_ms=since)
                        if not t["isBuyer"] and t["orderId"] not in mine and t["time"] >= since],
                       key=lambda t: t["time"])
        pool = [[float(t["qty"]), float(t["price"])] for t in sells]
        total = sum(p["qty"] for p in led["open"] if p["symbol"] == sym)
        gone = max(0.0, total - sum(bal.get(f["base"], (0.0, 0.0))) - sum(q for q, _ in pool))
        if sum(q for q, _ in pool) + gone <= step:
            continue
        if sells and not dry:
            seen[sym] = max(t["time"] for t in sells)
        cur = c.price(sym)
        for pos in users:
            got = val = 0.0
            while pool and got < pos["qty"] - 1e-12:
                take = min(pool[0][0], pos["qty"] - got)
                got, val = got + take, val + take * pool[0][1]
                pool[0][0] -= take
                if pool[0][0] <= 1e-12:
                    pool.pop(0)
            g = min(gone, pos["qty"] - got)
            gone -= g
            sold = got + g
            if sold <= step:
                continue
            px, reason = (val + g * cur) / sold, ("manual" if got else "gone")
            log(f"{sym}: bạn đã bán {sold:.8g} @ {X.num(px)}")
            if dry:
                continue
            rest = pos["qty"] - sold
            led["open"].remove(pos)
            X.close_pos(led, dict(pos), reason, sold, sold * px, msgs, tag)
            if rest * cur >= f["minNotional"]:
                led["open"].append(dict(pos, qty=rest, cost=pos["cost"] * rest / pos["qty"]))

    # 3) Mua lệnh giấy mở trong giờ này.
    known = {p["key"] for p in led["open"]} | {p["key"] for p in led["closed"][:300]}
    per = capital / sum(slots.values())
    usdt = bal.get(X.QUOTE, (0.0, 0.0))[0]
    for pid, it in popen.items():
        if pid in known or it["entryTs"] != bar_open.get(it["symbol"]):
            continue
        n = sum(1 for p in led["open"] if p["strategy"] == it["strategy"] and p["status"] == "bot")
        if n >= slots.get(it["strategy"], 0):
            continue
        sym = it["symbol"]
        if usdt < per:
            msgs.append(f"⚠️ Tín hiệu mua <b>{X.pair(sym)}</b> nhưng chỉ còn {usdt:.2f} USDT "
                        f"(cần {per:.2f}).{tag}")
            continue
        log(f"MUA {sym} {per:.2f} USDT ({it['strategy']})")
        if dry:
            continue
        f = c.filters(sym)
        cid = f"{short(pid)}B"
        o = c.order_by_cid(sym, cid) or c.market(sym, "BUY", cid, quote_qty=per)
        if o.get("status") != "FILLED":
            msgs.append(f"⚠️ Lệnh mua {X.pair(sym)} chưa khớp hết ({o.get('status')}).{tag}")
            continue
        q, cost = X.fill_of(c, sym, o, f["base"])
        usdt -= cost
        fill = cost / q
        pos = {"key": pid, "symbol": sym, "strategy": it["strategy"], "entryTs": it["entryTs"],
               "entryMs": o.get("transactTime") or o.get("time"), "entryTime": X.now_vn(),
               "qty": q, "cost": cost, "entryPrice": fill, "paperEntry": it["entry"],
               "paperStop0": it["stop"], "paperTp": it.get("tp"),
               "k": fill / it["entry"], "botOrderIds": [o["orderId"]], "status": "bot",
               "protect": None}
        stop = it["stop"] * pos["k"]
        tp = it["tp"] * pos["k"] if it.get("tp") else None
        led["open"].append(pos)
        X.save_ledger(led, path)      # đã mua: ghi ngay, lỡ bước đặt OCO lỗi cũng không mất dấu
        try:
            hit = place_protect(c, pos, f, stop, tp)
        except X.ApiError as e:
            msgs.append(f"⚠️ ĐÃ MUA {X.pair(sym)} nhưng chưa đặt được OCO ({e}). "
                        f"Giờ sau bot thử lại.{tag}")
            continue
        if hit:
            led["open"].remove(pos)
            if not sell_market(c, led, pos, hit, msgs, tag):
                led["open"].append(pos)
            continue
        st = C.STRATEGIES.get(it["strategy"], {})
        msgs.append(X.with_buttons("\n".join([
            f"✅ <b>ĐÃ MUA {X.pair(sym)}</b>{tag} · ⚡1h · {it['strategy']}",
            f"{X.num(q)} coin · giá {X.num(fill)} · {cost:.2f} USDT",
            f"OCO trên sàn: chốt lời {X.num(tp)} · cắt lỗ {X.num(stop)}" if tp
            else f"Cắt lỗ trên sàn: {X.num(stop)}",
            f"Trailing {C.EXIT['trailPct']:g}% · Giữ tối đa {C.EXIT['maxHold']}h"
            + (" · hoặc tới khi giá hồi về trung bình 24h" if st.get("exitFn") else ""),
            "Muốn chốt sớm: bấm Đóng bên dưới (hoặc huỷ OCO trên app rồi tự bán).",
            X.chart_link(sym),
        ]), X.close_buttons("d", pid, sym),
            {"kind": "buy", "note": X.note(), "it": {"symbol": sym, "strategy": it["strategy"], "entryTs": it["entryTs"],
                                   "entry": it["entry"], "stop0": it["stop"], "tp": it.get("tp")}}))

    if not dry:
        led["updatedAt"] = X.now_vn()
        X.save_ledger(led, path)
    return msgs


# ---------------------------------------------------------------------------
def cmd_status(c, path):
    led = X.load_ledger(path)
    print(f"Sổ bắt đáy ({led.get('mode', c.mode)}) · cập nhật {led.get('updatedAt', '—')}")
    for p in led["open"]:
        px = c.price(p["symbol"])
        pnl = p["qty"] * px - p["cost"]
        who = "BẠN giữ" if p["status"] == "user" else \
            f"cắt lỗ {X.num(p.get('liveStop'))} · chốt {X.num(p.get('liveTp'))}"
        print(f"  {p['symbol']:<10} {p['strategy']:<14} vào {X.num(p['entryPrice'])} · nay {X.num(px)}"
              f" · {pnl:+.2f} USDT · {who}")
    cl = led["closed"]
    if cl:
        print(f"  đã đóng {len(cl)} lệnh · tổng {sum(x.get('pnlUsdt') or 0 for x in cl):+.2f} USDT")


def close_one(c, key, path=None):
    """Đóng ngay một lệnh bắt đáy theo yêu cầu của bạn (nút Đóng trên Telegram):
    huỷ OCO nếu còn, bán market phần coin của lệnh. Trả về tin nhắn; rỗng nếu lệnh
    không còn mở (vd OCO vừa khớp xong)."""
    path = path or LEDGER
    led = X.load_ledger(path)
    pos = next((p for p in led["open"] if p["key"] == key), None)
    if not pos:
        return []
    tag = " · 🧪testnet" if c.mode == "testnet" else ""
    msgs = []
    if pos.get("protect"):
        # OCO có thể vừa khớp ngay trước khi bạn bấm — khi đó ghi theo giá sàn đã khớp.
        st, filled = protect_status(c, pos)
        if st == "filled":
            f = c.filters(pos["symbol"])
            q = quote = 0.0
            for o in filled:
                a, b = X.fill_of(c, pos["symbol"], o, f["base"])
                q, quote = q + a, quote + b
            led["open"].remove(pos)
            X.close_pos(led, pos, filled_reason(pos, filled), q, quote, msgs, tag)
            X.save_ledger(led, path)
            return msgs
        cancel_protect(c, pos)
    led["open"].remove(pos)
    if not sell_market(c, led, pos, "tg", msgs, tag):
        led["open"].append(pos)      # chưa bán được: vẫn giữ, giờ sau bot thử lại theo luật
    X.save_ledger(led, path)
    return msgs


def cmd_panic(c, path):
    led = X.load_ledger(path)
    msgs = []
    for pos in list(led["open"]):
        if pos["status"] == "user":
            print(f"  {pos['symbol']}: lệnh của bạn, bỏ qua", file=sys.stderr)
            continue
        cancel_protect(c, pos)
        led["open"].remove(pos)
        if not sell_market(c, led, pos, "panic", msgs, ""):
            led["open"].append(pos)
    X.save_ledger(led, path)
    print("\n".join(msgs) or "Không có gì để bán.")


TEST_LEDGER = os.path.join(CACHE, "live-dip-test.json")
TEST_PAPER = os.path.join(CACHE, "paper-dip-test.json")


def cmd_test(c, sym, action):
    """Thử trọn vòng trên testnet với một lệnh giấy giả, sổ riêng, không lẫn bot thật."""
    if c.mode != "testnet":
        print("Lệnh test chỉ chạy với LIVE_TRADING=testnet.", file=sys.stderr)
        return 1
    sym = sym.upper() + ("" if sym.upper().endswith(X.QUOTE) else X.QUOTE)
    paper = X.load_ledger(TEST_PAPER)
    it = next((i for i in paper["open"] if i["symbol"] == sym), None)
    px = c.price(sym)
    hour = int(time.time() // 3600) * 3600000

    if action == "buy":
        if it:
            print(f"Đã có lệnh giấy {sym} — chạy lại, bot phải KHÔNG mua trùng:")
        else:
            it = {"id": f"test-{sym}-{hour}", "symbol": sym, "strategy": "vcr", "entryTs": hour,
                  "entry": px, "stop": px * 0.95, "stop0": px * 0.95, "tp": px * 1.10,
                  "trailed": False}
            paper["open"].append(it)
    elif not it:
        print(f"Chưa có lệnh giấy {sym}. Chạy 'test {sym[:-4]}' trước.")
        return 1
    elif action == "trail":
        it["stop"], it["trailed"] = min(it["entry"], px) * 0.98, True
        print(f"Sổ giấy dời cắt lỗ lên {X.num(it['stop'])} — bot phải thay OCO.")
    elif action == "rule":
        paper["open"].remove(it)
        paper["closed"].insert(0, dict(it, exitReason="strategy"))
        print("Sổ giấy đóng lệnh (giá về trung bình 24h) — bot phải huỷ OCO và bán.")
    elif action == "manual":
        pos = next((p for p in X.load_ledger(TEST_LEDGER)["open"] if p["key"] == it["id"]), None)
        if not pos or not pos.get("protect"):
            print("Bot chưa có OCO cho lệnh này.")
            return 1
        cancel_protect(c, dict(pos))
        f = c.filters(sym)
        qty = X.floor_qty(pos["qty"], f["step"])
        o = c.market(sym, "SELL", f"user-{int(time.time())}", qty=qty)
        print(f"Giả làm bạn: huỷ OCO, bán tay {qty} (lệnh {o['orderId']}).")

    X.save_ledger(paper, TEST_PAPER)
    msgs = sync(paper, {sym: it["entryTs"]}, 120, {"vcr": 2}, client=c, path=TEST_LEDGER)
    print("\n\n".join(msgs) if msgs else "(bot không làm gì)")
    if action == "manual":       # lần chạy đầu thấy OCO bị huỷ, chạy tiếp để thấy bạn đã bán
        msgs = sync(paper, {sym: it["entryTs"]}, 120, {"vcr": 2}, client=c, path=TEST_LEDGER)
        print("\n\n".join(msgs) if msgs else "(bot không làm gì)")
    return 0


def main():
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["status", "panic", "test"])
    ap.add_argument("symbol", nargs="?", default="ENA")
    ap.add_argument("--yes", action="store_true")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--trail", action="store_true")
    g.add_argument("--manual", action="store_true")
    g.add_argument("--rule", action="store_true")
    args = ap.parse_args()
    try:
        c = X.Binance()
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 1
    if args.cmd == "status":
        cmd_status(c, LEDGER)
    elif args.cmd == "panic":
        if not args.yes:
            print("Thêm --yes để huỷ OCO và bán hết coin bot đang giữ.")
            return 1
        cmd_panic(c, LEDGER)
    else:
        act = "trail" if args.trail else "manual" if args.manual else "rule" if args.rule else "buy"
        return cmd_test(c, args.symbol, act)
    return 0


if __name__ == "__main__":
    sys.exit(main())
