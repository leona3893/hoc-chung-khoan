#!/usr/bin/env python3
"""
Điều khiển bot đặt lệnh qua Telegram. Trên VPS chạy liên tục (systemd, --loop) bằng long
polling: giữ một kết nối chờ Telegram, có tin là nhận ngay — bấm nút là phản hồi tức thì.
Đọc bạn vừa gõ gì / bấm nút nào, rồi làm:

    /lenh              lệnh đang mở của cả hai bot, mỗi lệnh một nút Đóng
    /dong ENA          đóng lệnh ENA (hỏi xác nhận)
    /dongall           đóng tất cả (hỏi xác nhận)
    nút 🔴 Đóng lệnh này (gắn sẵn dưới mỗi tin ĐÃ MUA) → hỏi xác nhận → đóng

Đóng = huỷ OCO nếu có, bán market phần coin của lệnh đó. Bot ghi lý do "bạn đóng qua
Telegram" và không mua lại lệnh đó.

An toàn:
    • Chỉ nhận lệnh từ đúng TELEGRAM_CHAT_ID — người khác nhắn bot thì bị lờ đi.
    • Không mở cổng nào trên VPS: máy tự hỏi Telegram (getUpdates), không ai gọi vào được.
    • Mọi lệnh đóng đều phải bấm xác nhận lần hai.
    • Dùng chung khoá /tmp/bot.lock với run.sh nên không bao giờ đụng sổ cùng lúc.

    python3 scripts/tg_control.py          # một lượt: xử lý tin mới rồi thoát
    python3 scripts/tg_control.py --loop   # chạy liên tục (dịch vụ bot-tg trên VPS)
"""

import html
import json
import os
import sys
import time
import urllib.request
from contextlib import contextmanager

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import exchange as X  # noqa: E402
import live_dip as LD  # noqa: E402

try:
    import fcntl
except ImportError:      # Windows — chỉ để chạy thử ở máy, VPS là Linux
    fcntl = None

OFFSET = os.environ.get("TG_OFFSET_STATE") or os.path.join(os.path.dirname(LD.LEDGER), "tg-offset.json")
LOCK = "/tmp/bot.lock"
BOT = {"d": "bắt đáy", "t": "xu hướng"}

HELP = ("🤖 <b>Điều khiển bot</b>\n"
        "/lenh — lệnh đang mở, kèm nút Đóng\n"
        "/dong ENA — đóng lệnh ENA\n"
        "/dongall — đóng tất cả\n"
        "Mọi lệnh đóng đều hỏi xác nhận trước.")


def api(method, _timeout=30, **params):
    tok = os.environ["TELEGRAM_BOT_TOKEN"].strip()
    req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/{method}",
                                 data=json.dumps(params).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=_timeout) as r:
        return json.load(r)


def client():
    return X.Binance()


def real_price(sym):
    """Giá thị trường thật (API công khai, không cần khoá), bất kể bot đang ở testnet hay không."""
    url = f"https://data-api.binance.vision/api/v3/ticker/price?symbol={sym}"
    with urllib.request.urlopen(url, timeout=10) as r:
        return float(json.load(r)["price"])


def send(chat, text, rows=None):
    p = {"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if rows:
        p["reply_markup"] = {"inline_keyboard": rows}
    return api("sendMessage", **p)


def edit(chat, msg_id, text):
    try:
        api("editMessageText", chat_id=chat, message_id=msg_id, text=text, parse_mode="HTML")
    except Exception:  # noqa: BLE001 — tin quá cũ không sửa được thì thôi
        pass


@contextmanager
def bot_lock(wait=300):
    """Chờ run.sh chạy xong (nếu đang chạy) rồi mới đụng vào sổ."""
    if fcntl is None:
        yield
        return
    f = open(LOCK, "w")
    t0 = time.time()
    while True:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if time.time() - t0 > wait:
                f.close()
                raise RuntimeError("bot đang bận quá lâu, thử lại sau")
            time.sleep(2)
    try:
        yield
    finally:
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()


# ---------------------------------------------------------------------------
def positions():
    out = []
    for b, path in (("d", LD.LEDGER), ("t", X.LEDGER)):
        out += [(b, p) for p in X.load_ledger(path)["open"]]
    return out


def find(b, s):
    return next(((bb, p) for bb, p in positions() if bb == b and X.sid(p["key"]) == s), None)


def name(b, p):
    return f"<b>{X.pair(p['symbol'])}</b> ({BOT[b]})"


def list_view():
    ps = positions()
    if not ps:
        return "📭 Không có lệnh nào đang mở.", None
    c = client()
    test = c.mode == "testnet"
    lines, rows = [f"📊 <b>Lệnh đang mở ({len(ps)})</b>" + (" · 🧪testnet" if test else "")], []
    for b, p in ps:
        entry = p["entryPrice"]
        try:
            if test:
                # Giá testnet chỉ nhúc nhích khi có người khớp lệnh trên testnet — có giờ
                # không ai giao dịch, giá đứng im. Nên lấy GIÁ THẬT để bạn so với chart,
                # tính % theo giá vào của sổ giấy (giá thật lúc có tín hiệu).
                real = real_price(p["symbol"])
                base = entry = p.get("paperEntry") or p["entryPrice"]
                tpx = c.price(p["symbol"])
                tpnl = p["qty"] * tpx - p["cost"]
                now = (f"giá thật {X.num(real)} · <b>{(real / base - 1) * 100:+.2f}%</b>\n"
                       f"<i>testnet {X.num(tpx)} · {tpnl:+.2f} USDT</i>")
            else:
                px = c.price(p["symbol"])
                pnl = p["qty"] * px - p["cost"]
                now = f"nay {X.num(px)} · <b>{pnl:+.2f} USDT ({pnl / p['cost'] * 100:+.2f}%)</b>"
        except Exception:  # noqa: BLE001
            now = "chưa lấy được giá"
        if p.get("status") == "user":
            extra = "bạn đã giành quyền (huỷ OCO trên app)"
        elif p.get("liveStop"):
            extra = f"cắt lỗ {X.num(p['liveStop'])} · chốt {X.num(p.get('liveTp'))}"
        else:
            extra = ""
        lines.append(f"\n{name(b, p)}" + (f" · {p['strategy']}" if b == "d" else "")
                     + f"\nvào {X.num(entry)} · {now}" + (f"\n{extra}" if extra else "")
                     + f"\n{X.chart_link(p['symbol'])}")
        rows.append([{"text": f"🔴 Đóng {p['symbol'].replace(X.QUOTE, '')} ({BOT[b]})",
                      "callback_data": f"c:{b}:{X.sid(p['key'])}"}])
    if len(ps) > 1:
        rows.append([{"text": "⛔ Đóng tất cả", "callback_data": "A"}])
    rows.append([{"text": "🔄 Làm mới", "callback_data": "l"}])
    return "\n".join(lines), rows


def confirm_one(chat, b, p):
    send(chat, f"Đóng {name(b, p)} ngay bây giờ?\nHuỷ OCO (nếu có) rồi bán market.",
         [[{"text": "✅ Đóng", "callback_data": f"y:{b}:{X.sid(p['key'])}"},
           {"text": "Huỷ", "callback_data": "n"}]])


def close(items):
    """Đóng các lệnh [(bot, pos)]. Trả về tin nhắn kết quả."""
    c = client()
    msgs = []
    with bot_lock():
        for b, p in items:
            try:
                r = LD.close_one(c, p["key"]) if b == "d" else X.close_one(c, p["key"])
                msgs += r or [f"ℹ️ {name(b, p)} không còn mở (sàn vừa khớp hoặc đã đóng)."]
            except Exception as e:  # noqa: BLE001
                msgs.append(f"❗ Không đóng được {name(b, p)}: {html.escape(str(e)[:200])}")
    return msgs


# ---------------------------------------------------------------------------
def on_message(chat, text):
    parts = text.strip().split()
    cmd = parts[0].split("@")[0].lower() if parts else ""
    if cmd in ("/lenh", "/start"):
        if cmd == "/start":
            send(chat, HELP)
        send(chat, *list_view())
    elif cmd == "/dongall":
        n = len(positions())
        if not n:
            send(chat, "📭 Không có lệnh nào đang mở.")
        else:
            send(chat, f"⛔ Đóng <b>TẤT CẢ {n} lệnh</b> đang mở?",
                 [[{"text": f"✅ Đóng hết {n} lệnh", "callback_data": "Y"},
                   {"text": "Huỷ", "callback_data": "n"}]])
    elif cmd == "/dong":
        sym = (parts[1].upper() if len(parts) > 1 else "")
        sym += "" if not sym or sym.endswith(X.QUOTE) else X.QUOTE
        hits = [(b, p) for b, p in positions() if p["symbol"] == sym]
        if not sym:
            send(chat, "Gõ kèm mã, vd: <code>/dong ENA</code>. Hoặc /lenh để chọn bằng nút.")
        elif not hits:
            send(chat, f"Không có lệnh {html.escape(sym)} nào đang mở. Gõ /lenh để xem.")
        elif len(hits) == 1:
            confirm_one(chat, *hits[0])
        else:
            send(chat, f"{html.escape(sym)} đang có {len(hits)} lệnh — chọn lệnh muốn đóng:",
                 [[{"text": f"🔴 {BOT[b]} · vào {X.num(p['entryPrice'])}",
                    "callback_data": f"c:{b}:{X.sid(p['key'])}"}] for b, p in hits])
    else:
        send(chat, HELP)


def on_callback(chat, msg_id, data):
    if data == "l":
        send(chat, *list_view())
    elif data == "n":
        edit(chat, msg_id, "Đã huỷ — không đóng gì.")
    elif data == "A":
        n = len(positions())
        send(chat, f"⛔ Đóng <b>TẤT CẢ {n} lệnh</b> đang mở?",
             [[{"text": f"✅ Đóng hết {n} lệnh", "callback_data": "Y"},
               {"text": "Huỷ", "callback_data": "n"}]])
    elif data == "Y":
        edit(chat, msg_id, "⏳ Đang đóng tất cả…")
        for m in close(positions()) or ["📭 Không có lệnh nào đang mở."]:
            send(chat, m)
    elif data[:2] in ("c:", "y:"):
        _, b, s = data.split(":")
        hit = find(b, s)
        if not hit:
            send(chat, "ℹ️ Lệnh này không còn mở (sàn vừa khớp hoặc đã đóng).")
        elif data[0] == "c":
            confirm_one(chat, *hit)
        else:
            edit(chat, msg_id, f"⏳ Đang đóng {name(*hit)}…")
            for m in close([hit]):
                send(chat, m)


def handle(u, chat_id):
    """Một update của Telegram. Chỉ xử lý nếu đến từ đúng chat của bạn."""
    if "callback_query" in u:
        cq = u["callback_query"]
        msg = cq.get("message") or {}
        if str(msg.get("chat", {}).get("id")) != chat_id:
            return
        api("answerCallbackQuery", callback_query_id=cq["id"])
        print(f"  [tg] nút {cq.get('data')}", file=sys.stderr)
        on_callback(chat_id, msg.get("message_id"), cq.get("data") or "")
    elif "message" in u:
        m = u["message"]
        if str(m.get("chat", {}).get("id")) != chat_id or not m.get("text"):
            return
        print(f"  [tg] tin {m['text'][:40]!r}", file=sys.stderr)
        on_message(chat_id, m["text"])


def save_offset(n):
    os.makedirs(os.path.dirname(OFFSET), exist_ok=True)
    with open(OFFSET, "w", encoding="utf-8") as f:
        json.dump({"offset": n}, f)


def poll(chat, wait=0):
    """Một lượt: lấy tin mới rồi xử lý. wait > 0 = long polling: Telegram giữ kết nối
    tới `wait` giây và trả về NGAY khi có tin — nên bấm nút là bot phản hồi tức thì."""
    first = not os.path.exists(OFFSET)
    off = 0 if first else json.load(open(OFFSET, encoding="utf-8")).get("offset", 0)
    ups = api("getUpdates", _timeout=wait + 15, offset=off, timeout=0 if first else wait,
              allowed_updates=["message", "callback_query"]).get("result", [])
    save = save_offset

    if first:
        # Lần đầu: đăng ký menu lệnh, bỏ qua tin cũ tồn đọng (không làm theo lệnh của hôm qua).
        api("setMyCommands", commands=[
            {"command": "lenh", "description": "Lệnh đang mở, kèm nút Đóng"},
            {"command": "dong", "description": "Đóng một lệnh, vd /dong ENA"},
            {"command": "dongall", "description": "Đóng tất cả lệnh"}])
        save(max([u["update_id"] for u in ups], default=-1) + 1)
        send(chat, HELP)
        print("Đã bật điều khiển Telegram.", file=sys.stderr)
        return 0

    for u in ups:
        # Ghi mốc TRƯỚC khi làm: lỡ lỗi giữa chừng thì lần sau không lặp lại lệnh đóng.
        save(u["update_id"] + 1)
        try:
            handle(u, chat)
        except Exception as e:  # noqa: BLE001
            print(f"  [tg] LỖI: {e}", file=sys.stderr)
            try:
                send(chat, f"❗ Lỗi: {html.escape(str(e)[:300])}")
            except Exception:  # noqa: BLE001
                pass
    return 0


def main():
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8", errors="replace")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not os.environ.get("TELEGRAM_BOT_TOKEN", "").strip() or not chat:
        print("Chưa có TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID.", file=sys.stderr)
        return 1
    if "--loop" not in sys.argv:
        return poll(chat)
    # Chạy liên tục (systemd giữ cho sống, khởi động lại mỗi giờ để nạp code mới).
    print("Điều khiển Telegram: đang lắng nghe.", file=sys.stderr, flush=True)
    while True:
        try:
            poll(chat, wait=50)
        except Exception as e:  # noqa: BLE001 — mất mạng, Telegram lỗi: nghỉ chút rồi thử lại
            print(f"  [tg] mất kết nối: {str(e)[:120]}", file=sys.stderr, flush=True)
            time.sleep(5)


if __name__ == "__main__":
    sys.exit(main())
