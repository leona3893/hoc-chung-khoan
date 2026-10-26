#!/usr/bin/env python3
"""
Đặt lệnh thật (hoặc testnet) trên Binance Spot cho bot xu hướng.

Nguyên tắc:

    • Sổ GIẤY của trend_bot.py là nơi ra quyết định. File này chỉ làm theo:
      sổ giấy mở lệnh hôm nay  →  mua thật;  sổ giấy đóng lệnh theo luật  →  bán thật.
    • Bot chỉ bán đúng phần coin NÓ đã mua. Coin bạn có sẵn từ trước không bị đụng tới.
    • Bạn được chốt tay bất cứ lúc nào trên app Binance. Lần chạy sau bot thấy số dư
      hụt, ghi nhận "chốt tay" kèm giá bạn bán, rồi thôi theo dõi lệnh đó — và KHÔNG
      mua lại mã đó cho tới khi có tín hiệu mới.
    • Bot không đặt lệnh chờ (cắt lỗ/chốt lời) trên sàn, nên coin không bị khoá:
      bán tay lúc nào cũng được. Luật thoát tính trên nến ngày, đúng như backtest.
    • Bot không bao giờ huỷ hay sửa lệnh do bạn tự đặt.

Bật bằng biến môi trường, mặc định TẮT:

    LIVE_TRADING=off | testnet | live
    BINANCE_API_KEY=...
    BINANCE_API_SECRET=...
    LIVE_STATE=đường/dẫn/live-trend.json   (tuỳ chọn, mặc định data/cache/live-trend.json)

    python scripts/exchange.py check     # kiểm tra key, quyền, số dư
    python scripts/exchange.py status    # các lệnh bot đang giữ, lời/lỗ hiện tại
    python scripts/exchange.py panic --yes   # bán hết coin BOT đang giữ (khẩn cấp)

Ở chế độ live, bot TỪ CHỐI đặt lệnh nếu key có quyền rút tiền.
"""

import argparse
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import ROUND_DOWN, Decimal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_env(path=os.path.join(ROOT, ".env")):
    """Đọc KEY=VALUE từ .env ở gốc repo (đã gitignore). Biến đã đặt sẵn thì giữ nguyên."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip().removeprefix("export ").strip()
            os.environ.setdefault(k, v.strip().strip('"').strip("'"))


load_env()
LEDGER = os.environ.get("LIVE_STATE") or os.path.join(ROOT, "data", "cache", "live-trend.json")

HOSTS = {"testnet": "https://testnet.binance.vision", "live": "https://api.binance.com"}
QUOTE = "USDT"
VN_TZ = timezone(timedelta(hours=7))

EXIT_LABEL = {"rule": "xu hướng gãy (luật)", "manual": "bạn chốt tay",
              "tg": "bạn đóng qua Telegram",
              "panic": "bán khẩn cấp", "dust": "còn quá ít để bán",
              "gone": "số dư biến mất"}
BY_USER = ("manual", "tg")


class Msg(str):
    """Tin nhắn kèm nút Telegram và/hoặc ảnh chart. Vẫn là chuỗi — chỗ nào dùng chuỗi đều
    dùng được. Hàm gửi tin thấy .buttons thì gắn bàn phím nút; bot thấy .chart thì vẽ ảnh
    (cần nến, nên bot vẽ chứ không phải file này)."""
    buttons = None
    chart = None      # {"kind": "buy"|"sell", "it": {symbol, strategy, entry, stop0, tp, ...}}


def with_buttons(text, rows, chart=None):
    m = Msg(text)
    m.buttons = rows
    m.chart = chart
    return m


def with_chart(text, chart):
    m = Msg(text)
    m.chart = chart
    return m


def real_px(pos, px):
    """Đổi giá trên sàn đang chạy về giá thị trường thật để vẽ lên chart nến thật.
    Testnet lệch giá thật; k = giá khớp / giá sổ giấy lúc mua (sàn thật thì k = 1)."""
    return px / pos.get("k", 1) if px else px


def sid(key):
    """Mã ngắn của một lệnh, đủ gọn để nhét vào nút Telegram (tối đa 64 byte)."""
    return hashlib.md5(key.encode()).hexdigest()[:10]


def chart_url(sym):
    base = sym[:-len(QUOTE)] if sym.endswith(QUOTE) else sym
    return f"https://www.binance.com/vi/trade/{base}_{QUOTE}?type=spot"


def chart_link(sym):
    """Link mở thẳng chart trên Binance — điện thoại có app Binance thì mở trong app."""
    return f'<a href="{chart_url(sym)}">📈 Chart {sym.replace(QUOTE, "")} trên Binance</a>'


def close_buttons(bot, key, sym):
    """bot: "d" = bắt đáy, "t" = xu hướng."""
    return [[{"text": "🔴 Đóng lệnh này", "callback_data": f"c:{bot}:{sid(key)}"},
             {"text": "📈 Chart", "url": chart_url(sym)}],
            [{"text": "📊 Lệnh đang mở", "callback_data": "l"}]]


def mode():
    m = os.environ.get("LIVE_TRADING", "off").strip().lower()
    return m if m in HOSTS else "off"


def enabled():
    return mode() != "off"


def note():
    """Chú thích cuối ảnh chart của lệnh trên sàn (ảnh sổ giấy ghi "sổ giấy")."""
    return "lệnh của bot · testnet, tiền ảo" if mode() == "testnet" else "lệnh tiền thật của bot"


class ApiError(Exception):
    def __init__(self, code, msg):
        super().__init__(f"{code}: {msg}")
        self.code = code


# ---------------------------------------------------------------------------
class Binance:
    """Client tối thiểu cho Spot API, chỉ dùng urllib."""

    def __init__(self, m=None):
        self.mode = m or mode()
        if self.mode not in HOSTS:
            raise RuntimeError("LIVE_TRADING chưa bật (testnet hoặc live).")
        self.base = HOSTS[self.mode]
        self.key = os.environ.get("BINANCE_API_KEY", "").strip()
        self.secret = os.environ.get("BINANCE_API_SECRET", "").strip()
        if not self.key or not self.secret:
            raise RuntimeError("Thiếu BINANCE_API_KEY hoặc BINANCE_API_SECRET.")
        self._offset = None
        self._info = {}

    def _call(self, method, path, params=None, signed=False):
        params = dict(params or {})
        if signed:
            if self._offset is None:
                srv = self._call("GET", "/api/v3/time")["serverTime"]
                self._offset = srv - int(time.time() * 1000)
            params["timestamp"] = int(time.time() * 1000) + self._offset
            params["recvWindow"] = 5000
        q = urllib.parse.urlencode(params)
        if signed:
            sig = hmac.new(self.secret.encode(), q.encode(), hashlib.sha256).hexdigest()
            q += "&signature=" + sig
        req = urllib.request.Request(self.base + path + ("?" + q if q else ""), method=method,
                                     headers={"X-MBX-APIKEY": self.key})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            try:
                j = json.loads(body)
                raise ApiError(j.get("code"), j.get("msg")) from None
            except ValueError:
                raise ApiError(e.code, body[:200]) from None

    # --- thông tin
    def filters(self, symbol):
        if symbol not in self._info:
            s = self._call("GET", "/api/v3/exchangeInfo", {"symbol": symbol})["symbols"][0]
            f = {x["filterType"]: x for x in s["filters"]}
            notional = f.get("NOTIONAL") or f.get("MIN_NOTIONAL") or {}
            self._info[symbol] = {
                "base": s["baseAsset"],
                "step": Decimal(f["LOT_SIZE"]["stepSize"]),
                "minQty": Decimal(f["LOT_SIZE"]["minQty"]),
                "minNotional": float(notional.get("minNotional", 5)),
                "tick": Decimal(f["PRICE_FILTER"]["tickSize"]),
            }
        return self._info[symbol]

    def balances(self):
        acct = self._call("GET", "/api/v3/account", {"omitZeroBalances": "true"}, signed=True)
        return {b["asset"]: (float(b["free"]), float(b["locked"])) for b in acct["balances"]}

    def price(self, symbol):
        return float(self._call("GET", "/api/v3/ticker/price", {"symbol": symbol})["price"])

    def restrictions(self):
        """Quyền của key (chỉ có trên sàn thật)."""
        return self._call("GET", "/sapi/v1/account/apiRestrictions", signed=True)

    # --- lệnh
    def order_by_cid(self, symbol, cid):
        try:
            return self._call("GET", "/api/v3/order",
                              {"symbol": symbol, "origClientOrderId": cid}, signed=True)
        except ApiError as e:
            if e.code == -2013:           # chưa có lệnh này
                return None
            raise

    def market(self, symbol, side, cid, quote_qty=None, qty=None):
        p = {"symbol": symbol, "side": side, "type": "MARKET",
             "newClientOrderId": cid, "newOrderRespType": "FULL"}
        if quote_qty is not None:
            p["quoteOrderQty"] = f"{quote_qty:.2f}"
        else:
            p["quantity"] = qty
        return self._call("POST", "/api/v3/order", p, signed=True)

    def trades(self, symbol, start_ms=None, order_id=None):
        p = {"symbol": symbol, "limit": 1000}
        if order_id is not None:
            p["orderId"] = order_id
        elif start_ms:
            p["startTime"] = start_ms
        return self._call("GET", "/api/v3/myTrades", p, signed=True)

    # --- lệnh chờ bảo vệ (OCO: chốt lời LIMIT_MAKER phía trên + cắt lỗ STOP_LOSS phía dưới)
    def oco(self, symbol, qty, tp, stop, cid):
        """Cắt lỗ là STOP_LOSS loại market: chạm là khớp chắc, kể cả lúc giá lao."""
        return self._call("POST", "/api/v3/orderList/oco", {
            "symbol": symbol, "side": "SELL", "quantity": qty,
            "aboveType": "LIMIT_MAKER", "abovePrice": tp,
            "belowType": "STOP_LOSS", "belowStopPrice": stop,
            "listClientOrderId": cid, "newOrderRespType": "FULL"}, signed=True)

    def stop_order(self, symbol, qty, stop, cid):
        """Chỉ cắt lỗ, khi chiến lược không có chốt lời."""
        return self._call("POST", "/api/v3/order", {
            "symbol": symbol, "side": "SELL", "type": "STOP_LOSS", "quantity": qty,
            "stopPrice": stop, "newClientOrderId": cid}, signed=True)

    def order_list(self, list_id):
        return self._call("GET", "/api/v3/orderList", {"orderListId": list_id}, signed=True)

    def order(self, symbol, order_id):
        return self._call("GET", "/api/v3/order", {"symbol": symbol, "orderId": order_id}, signed=True)

    def cancel_list(self, symbol, list_id):
        return self._call("DELETE", "/api/v3/orderList",
                          {"symbol": symbol, "orderListId": list_id}, signed=True)

    def cancel_order(self, symbol, order_id):
        return self._call("DELETE", "/api/v3/order", {"symbol": symbol, "orderId": order_id},
                          signed=True)


# ---------------------------------------------------------------------------
def floor_qty(qty, step):
    q = (Decimal(str(qty)) / step).to_integral_value(rounding=ROUND_DOWN) * step
    return format(q.normalize(), "f") if q else "0"


def fill_of(client, symbol, order, base):
    """(số coin thực nhận/bán, số USDT thực chi/thu) sau phí, từ một lệnh đã khớp."""
    fills = order.get("fills")
    if not fills:
        fills = [{"price": t["price"], "qty": t["qty"], "commission": t["commission"],
                  "commissionAsset": t["commissionAsset"]}
                 for t in client.trades(symbol, order_id=order["orderId"])]
    qty = sum(float(f["qty"]) for f in fills)
    quote = sum(float(f["qty"]) * float(f["price"]) for f in fills)
    fee_base = sum(float(f["commission"]) for f in fills if f["commissionAsset"] == base)
    fee_quote = sum(float(f["commission"]) for f in fills if f["commissionAsset"] == QUOTE)
    if order["side"] == "BUY":
        return qty - fee_base, quote + fee_quote
    return qty, quote - fee_quote


def cid_for(it, side):
    """Mã lệnh cố định theo lệnh giấy: chạy lại bao nhiêu lần cũng không mua trùng."""
    return f"tb-{it['symbol']}-{it['entryTs'] // 1000}-{side}"


def key_of(it):
    return f"{it['symbol']}-{it['entryTs']}"


def load_ledger(path=None):
    path = path or LEDGER
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {"open": [], "closed": []}


def save_ledger(led, path=None):
    path = path or LEDGER
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(led, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def now_vn():
    return datetime.now(VN_TZ).strftime("%Y-%m-%d %H:%M")


def pair(sym):
    return sym.replace(QUOTE, "/" + QUOTE)


def num(p):
    if p is None:
        return "—"
    if p >= 1000:
        return f"{p:,.0f}"
    if p >= 1:
        return f"{p:,.3f}".rstrip("0").rstrip(".")
    return f"{p:.6f}".rstrip("0")


def close_pos(led, pos, reason, qty, quote, msgs, tag):
    """Đóng (một phần hoặc cả) vị thế: ghi lời/lỗ thật theo giá vốn bình quân."""
    cost = pos["cost"] * (qty / pos["qty"]) if pos["qty"] else 0
    pnl = quote - cost
    rec = dict(pos, status="closed", exitReason=reason, exitTime=now_vn(),
               exitQty=qty, exitPrice=(quote / qty if qty else None),
               exitMs=int(time.time() * 1000),
               pnlUsdt=round(pnl, 4), pnlPct=round(pnl / cost * 100, 2) if cost else None)
    led["closed"].insert(0, rec)
    msgs.append(with_chart("\n".join([
        f"{'🙋' if reason in BY_USER else '✅'} <b>ĐÃ BÁN {pair(pos['symbol'])}</b>{tag}",
        f"{num(qty)} coin · giá {num(rec['exitPrice'])} · vốn vào {num(pos['entryPrice'])}",
        f"Lời/lỗ: <b>{pnl:+.2f} USDT</b> ({rec['pnlPct'] or 0:+.2f}%)",
        f"Lý do: {EXIT_LABEL.get(reason, reason)}",
    ] + (["Bot thôi theo dõi lệnh này, không mua lại mã này tới tín hiệu mới."]
         if reason in BY_USER else []) + [chart_link(pos["symbol"])]),
        {"kind": "sell", "note": note(), "it": {
            "symbol": pos["symbol"], "strategy": pos.get("strategy", "trend"),
            "entryTs": pos["entryTs"], "entry": pos.get("paperEntry") or pos["entryPrice"],
            "stop0": pos.get("paperStop0") or pos.get("exitLevel"), "tp": pos.get("paperTp"),
            "exitLevel": pos.get("exitLevel"),
            "exitPrice": real_px(pos, rec["exitPrice"]), "pnlPct": rec["pnlPct"]}}))


def close_one(c, key, path=None):
    """Đóng ngay một lệnh xu hướng theo yêu cầu của bạn (nút Đóng trên Telegram).
    Trả về danh sách tin nhắn; rỗng nếu lệnh không còn mở."""
    led = load_ledger(path)
    pos = next((p for p in led["open"] if p["key"] == key), None)
    if not pos:
        return []
    tag = " · 🧪testnet" if c.mode == "testnet" else ""
    msgs = []
    f = c.filters(pos["symbol"])
    free = c.balances().get(f["base"], (0.0, 0.0))[0]
    qty = floor_qty(min(pos["qty"], free), f["step"])
    px = c.price(pos["symbol"])
    led["open"].remove(pos)
    if float(qty) * px < f["minNotional"]:
        close_pos(led, pos, "dust", float(qty) or pos["qty"], (float(qty) or pos["qty"]) * px, msgs, tag)
    else:
        o = c.market(pos["symbol"], "SELL", f"{cid_for(pos, 'M')}{int(time.time()) % 10000}", qty=qty)
        if float(o.get("executedQty") or 0) <= 0:
            # Không ai mua (sổ lệnh mỏng, hay gặp trên testnet): giữ nguyên lệnh trong sổ.
            led["open"].append(pos)
            msgs.append(f"⚠️ Bán {pair(pos['symbol'])} không khớp — sổ lệnh"
                        f"{' testnet' if c.mode == 'testnet' else ''} không có người mua. "
                        f"Lệnh vẫn mở, bấm Đóng lại sau.{tag}")
        else:
            q, quote = fill_of(c, pos["symbol"], o, f["base"])
            close_pos(led, pos, "tg", q, quote, msgs, tag)
    save_ledger(led, path)
    return msgs


def guard(c, log):
    """Sàn thật: từ chối chạy nếu key có quyền rút tiền."""
    r = c.restrictions()
    if r.get("enableWithdrawals"):
        raise RuntimeError("Key đang bật quyền RÚT TIỀN — tắt quyền đó trên Binance rồi chạy lại. "
                           "Bot không đặt lệnh với key này.")
    if not r.get("ipRestrict"):
        log("cảnh báo: key chưa khoá theo IP.")


# ---------------------------------------------------------------------------
def sync(paper, bar_open, prices, capital, max_open, client=None, dry=False):
    """Đưa tài khoản thật về khớp với sổ giấy. Trả về danh sách tin nhắn.

    paper     sổ giấy của trend_bot (dict có "open", "closed")
    bar_open  {symbol: mốc mở nến ngày hiện tại} — chỉ mua lệnh giấy mở HÔM NAY
    prices    {symbol: giá hiện tại}
    """
    c = client or Binance()
    tag = " · 🧪testnet" if c.mode == "testnet" else ""
    msgs, log = [], (lambda s: print(f"  [sàn] {s}", file=sys.stderr))

    if c.mode == "live" and not dry:
        guard(c, log)

    led = load_ledger()
    led["mode"] = c.mode
    bal = c.balances()
    paper_open = {key_of(it): it for it in paper.get("open", [])}
    paper_closed = {key_of(it) for it in paper.get("closed", [])}

    # 1) Phát hiện chốt tay: coin của bot hụt so với sổ.
    still = []
    for pos in led["open"]:
        f = c.filters(pos["symbol"])
        free, locked = bal.get(f["base"], (0.0, 0.0))
        held = free + locked
        if held >= pos["qty"] - float(f["step"]):
            still.append(pos)
            continue
        sold = pos["qty"] - held
        mine = set(pos.get("botOrderIds", []))
        sells = [t for t in c.trades(pos["symbol"], start_ms=pos.get("sinceMs") or pos["entryMs"])
                 if not t["isBuyer"] and t["orderId"] not in mine]
        if sells:
            # Lấy các lệnh bán GẦN NHẤT, vừa đủ số coin bị hụt — lệnh bán cũ hơn có thể
            # là bạn bán coin riêng của mình, không phải của bot.
            got, val = 0.0, 0.0
            for t in sorted(sells, key=lambda t: t["time"], reverse=True):
                q = min(float(t["qty"]), sold - got)
                got, val = got + q, val + q * float(t["price"])
                if got >= sold - 1e-12:
                    break
            px = val / got
            reason = "manual"
        else:
            # Không thấy lệnh bán nào: bạn chuyển coin đi, dùng Convert, hoặc testnet bị reset.
            px = prices.get(pos["symbol"]) or c.price(pos["symbol"])
            reason = "gone"
        log(f"{pos['symbol']} hụt {sold:.8g} coin → {EXIT_LABEL[reason]} @ {num(px)}")
        if dry:
            still.append(pos)
            continue
        rest = dict(pos)
        close_pos(led, pos, reason, sold, sold * px, msgs, tag)
        if held * px >= f["minNotional"]:
            # Bạn chỉ chốt một phần: phần còn lại bot vẫn giữ và bán theo luật.
            rest["cost"] = pos["cost"] * held / pos["qty"]
            rest["qty"] = held
            if sells:      # lần sau chỉ xét các lệnh bán mới hơn
                rest["sinceMs"] = max(t["time"] for t in sells) + 1
            still.append(rest)
    led["open"] = still

    # 2) Bán theo luật: sổ giấy đã đóng lệnh này.
    still = []
    for pos in led["open"]:
        k = pos["key"]
        if k in paper_open:
            still.append(pos)
            continue
        if k not in paper_closed:
            # Sổ giấy không còn biết lệnh này (bị reset?). Không tự bán — báo bạn.
            log(f"{pos['symbol']} không có trong sổ giấy — giữ nguyên, cần xử lý tay.")
            if not pos.get("orphanWarned") and not dry:
                pos["orphanWarned"] = True
                msgs.append(f"⚠️ <b>{pair(pos['symbol'])}</b>: sổ giấy không còn lệnh này. "
                            f"Bot không tự bán. Dùng <code>exchange.py panic</code> hoặc bán tay.{tag}")
            still.append(pos)
            continue
        f = c.filters(pos["symbol"])
        free = bal.get(f["base"], (0.0, 0.0))[0]
        qty = floor_qty(min(pos["qty"], free), f["step"])
        px = prices.get(pos["symbol"]) or c.price(pos["symbol"])
        if float(qty) * px < f["minNotional"]:
            if bal.get(f["base"], (0, 0))[1] > 0:
                msgs.append(f"⚠️ Luật bảo bán <b>{pair(pos['symbol'])}</b> nhưng coin đang khoá "
                            f"trong lệnh bạn tự đặt. Bot không đụng vào lệnh của bạn.{tag}")
                still.append(pos)
                continue
            log(f"{pos['symbol']} còn quá ít ({qty}) để bán.")
            if not dry:
                close_pos(led, pos, "dust", float(qty) or pos["qty"], (float(qty) or pos["qty"]) * px,
                          msgs, tag)
            continue
        log(f"BÁN {pos['symbol']} {qty} (~{float(qty) * px:.2f} USDT)")
        if dry:
            still.append(pos)
            continue
        # Mã lệnh đổi theo số lần thử: lần trước hết hạn không khớp thì đặt lệnh MỚI,
        # còn lần trước đã khớp (bot chết trước khi ghi sổ) thì nhận lại đúng lệnh đó.
        cid = cid_for(pos, "S") + (str(pos["sellTry"]) if pos.get("sellTry") else "")
        o = c.order_by_cid(pos["symbol"], cid) or c.market(pos["symbol"], "SELL", cid, qty=qty)
        if o.get("status") != "FILLED":
            pos["sellTry"] = pos.get("sellTry", 0) + 1
            if pos["sellTry"] == 1:
                msgs.append(f"⚠️ Bán {pair(pos['symbol'])} theo luật không khớp ({o.get('status')}) — "
                            f"sổ lệnh không có người mua. Bot thử bán lại mỗi giờ.{tag}")
            still.append(pos)
            continue
        q, quote = fill_of(c, pos["symbol"], o, f["base"])
        close_pos(led, pos, "rule", q, quote, msgs, tag)
    led["open"] = still

    # 3) Mua theo lệnh giấy mở hôm nay.
    known = {p["key"] for p in led["open"]} | {p["key"] for p in led["closed"][:200]}
    per = capital / max_open
    for k, it in paper_open.items():
        if k in known or it["entryTs"] != bar_open.get(it["symbol"]):
            continue          # đã làm rồi, hoặc lệnh giấy cũ (bot bật giữa chừng)
        if len(led["open"]) >= max_open:
            break
        usdt = bal.get(QUOTE, (0.0, 0.0))[0]
        if usdt < per:
            msgs.append(f"⚠️ Tín hiệu mua <b>{pair(it['symbol'])}</b> nhưng chỉ còn "
                        f"{usdt:.2f} USDT (cần {per:.2f}).{tag}")
            continue
        log(f"MUA {it['symbol']} {per:.2f} USDT")
        if dry:
            continue
        f = c.filters(it["symbol"])
        cid = cid_for(it, "B")
        o = c.order_by_cid(it["symbol"], cid) or c.market(it["symbol"], "BUY", cid, quote_qty=per)
        if o.get("status") != "FILLED":
            msgs.append(f"⚠️ Lệnh mua {pair(it['symbol'])} chưa khớp hết ({o.get('status')}).{tag}")
            continue
        q, cost = fill_of(c, it["symbol"], o, f["base"])
        pos = {"key": k, "symbol": it["symbol"], "entryTs": it["entryTs"],
               "entryMs": o.get("transactTime") or o.get("time"), "entryTime": now_vn(),
               "qty": q, "cost": cost, "entryPrice": cost / q if q else None,
               "paperEntry": it["entry"], "k": (cost / q) / it["entry"] if q else 1,
               "exitLevel": it.get("exitLevel"),
               "botOrderIds": [o["orderId"]], "status": "open"}
        led["open"].append(pos)
        bal[QUOTE] = (usdt - cost, bal.get(QUOTE, (0, 0))[1])
        lvl = it.get("exitLevel")
        msgs.append(with_buttons("\n".join([
            f"✅ <b>ĐÃ MUA {pair(it['symbol'])}</b>{tag} · xu hướng 📈1D",
            f"{num(q)} coin · giá {num(pos['entryPrice'])} · {cost:.2f} USDT",
            (f"Ra khi nến ngày đóng dưới {num(lvl)} ({(lvl / it['entry'] - 1) * 100:+.1f}%) — "
             f"ngưỡng dời lên theo giá" if lvl else "Ra khi nến ngày đóng dưới ngưỡng thoát"),
            "Không giới hạn thời gian giữ — giữ tới khi xu hướng gãy.",
            chart_link(it["symbol"]),
        ]), close_buttons("t", k, it["symbol"]),
            {"kind": "buy", "note": note(), "it": {"symbol": it["symbol"], "strategy": it.get("strategy", "trend"),
                                   "entryTs": it["entryTs"], "entry": it["entry"],
                                   "exitLevel": lvl, "stop0": lvl}}))

    if not dry:
        led["updatedAt"] = now_vn()
        save_ledger(led)
    return msgs


# ---------------------------------------------------------------------------
def cmd_check(c):
    print(f"Chế độ: {c.mode} · {c.base}")
    if c.mode == "live":
        r = c.restrictions()
        print(f"  Spot trading: {'có' if r.get('enableSpotAndMarginTrading') else 'KHÔNG'}")
        print(f"  Rút tiền:     {'CÓ — PHẢI TẮT' if r.get('enableWithdrawals') else 'không'}")
        print(f"  Khoá IP:      {'có' if r.get('ipRestrict') else 'không — nên bật'}")
    for a, (fr, lk) in sorted(c.balances().items()):
        if fr + lk > 0 and (a == QUOTE or fr + lk > 1e-8):
            print(f"  {a:<8} free {fr:.8g} · locked {lk:.8g}")


def cmd_status(c):
    led = load_ledger()
    print(f"Sổ thật ({led.get('mode', c.mode)}) · cập nhật {led.get('updatedAt', '—')}")
    for p in led["open"]:
        px = c.price(p["symbol"])
        pnl = p["qty"] * px - p["cost"]
        print(f"  giữ {p['symbol']:<10} {p['qty']:.8g} · vào {num(p['entryPrice'])} · nay {num(px)}"
              f" · {pnl:+.2f} USDT ({pnl / p['cost'] * 100:+.2f}%)")
    cl = led["closed"]
    if cl:
        tot = sum(x.get("pnlUsdt") or 0 for x in cl)
        print(f"  đã đóng {len(cl)} lệnh · tổng {tot:+.2f} USDT")


def cmd_panic(c):
    led = load_ledger()
    msgs, still = [], []
    bal = c.balances()
    for pos in led["open"]:
        f = c.filters(pos["symbol"])
        qty = floor_qty(min(pos["qty"], bal.get(f["base"], (0, 0))[0]), f["step"])
        if float(qty) <= 0:
            print(f"  {pos['symbol']}: không có coin rảnh để bán", file=sys.stderr)
            still.append(pos)
            continue
        o = c.market(pos["symbol"], "SELL", cid_for(pos, "P"), qty=qty)
        q, quote = fill_of(c, pos["symbol"], o, f["base"])
        close_pos(led, pos, "panic", q, quote, msgs, "")
    led["open"] = still
    save_ledger(led)
    print("\n".join(msgs) or "Không có gì để bán.")


def cmd_test(c, sym, action):
    """Thử trọn vòng trên testnet, không cần chờ tín hiệu thật.

    Dùng sổ riêng (live-test.json) nên không lẫn với sổ của bot thật.
        test BTC            bot mua, như khi sổ giấy vừa mở lệnh hôm nay
        test BTC --manual   giả làm BẠN bán tay một nửa (lệnh không mang mã của bot)
        test BTC --rule     sổ giấy đóng lệnh theo luật → bot bán phần còn lại
    """
    global LEDGER
    if c.mode != "testnet":
        print("Lệnh test chỉ chạy với LIVE_TRADING=testnet.", file=sys.stderr)
        return 1
    LEDGER = os.path.join(os.path.dirname(LEDGER), "live-test.json")
    sym = sym.upper() + ("" if sym.upper().endswith(QUOTE) else QUOTE)
    px = c.price(sym)
    day = int(time.time() // 86400) * 86400000
    pos = next((p for p in load_ledger()["open"] if p["symbol"] == sym), None)
    it = {"symbol": sym, "entryTs": pos["entryTs"] if pos else day, "entry": px}

    if action == "manual":
        if not pos:
            print(f"Bot chưa giữ {sym}. Chạy 'test {sym[:-4]}' trước.")
            return 1
        f = c.filters(sym)
        qty = floor_qty(pos["qty"] / 2, f["step"])
        o = c.market(sym, "SELL", f"user-{int(time.time())}", qty=qty)
        print(f"Bạn bán tay {qty} {f['base']} (lệnh {o['orderId']}, không phải mã của bot).")
        paper = {"open": [it]}
    elif action == "rule":
        if not pos:
            print(f"Bot chưa giữ {sym}.")
            return 1
        paper = {"open": [], "closed": [it]}
    else:
        if pos:
            print(f"Bot đang giữ {sym} rồi — chạy lại không mua trùng:")
        paper = {"open": [it]}

    msgs = sync(paper, {sym: it["entryTs"]}, {sym: px}, 150, 5, client=c)
    print("\n\n".join(msgs) if msgs else "(bot không làm gì — đúng nếu không có gì thay đổi)")
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(), os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if msgs and tok and chat:
        import crypto_bot as B
        for m in msgs:
            B.tg_send(tok, chat, "🧪 <b>THỬ</b>\n" + m)
        print(f"(đã gửi {len(msgs)} tin Telegram)")
    return 0


def main():
    # Console Windows mặc định cp1252, in tiếng Việt là crash.
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["check", "status", "panic", "test"])
    ap.add_argument("symbol", nargs="?", default="BTC", help="cho lệnh test")
    ap.add_argument("--yes", action="store_true", help="xác nhận cho panic")
    ap.add_argument("--manual", action="store_true", help="test: giả làm bạn bán tay một nửa")
    ap.add_argument("--rule", action="store_true", help="test: luật bảo bán")
    args = ap.parse_args()
    try:
        c = Binance()
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 1
    if args.cmd == "test":
        return cmd_test(c, args.symbol, "manual" if args.manual else "rule" if args.rule else "buy")
    if args.cmd == "check":
        cmd_check(c)
    elif args.cmd == "status":
        cmd_status(c)
    elif args.cmd == "panic":
        if not args.yes:
            print("Thêm --yes để bán hết coin bot đang giữ.")
            return 1
        cmd_panic(c)
    return 0


if __name__ == "__main__":
    sys.exit(main())
