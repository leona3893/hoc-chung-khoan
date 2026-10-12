#!/usr/bin/env python3
"""
Lấy chat id của bạn và thử gửi một tin, để khỏi phải tự gọi curl.

Cách dùng:
  1. Nhắn cho @BotFather:  /newbot  → nó trả về token dạng 8123456789:AAH...
  2. Mở Telegram, nhắn MỘT CÂU BẤT KỲ cho bot vừa tạo (ví dụ "hi").
     Bot không gửi được tin cho người chưa từng nhắn nó trước.
  3. Chạy:

       python scripts/telegram_setup.py 8123456789:AAH...

     Script in ra chat id tìm được và gửi thử một tin vào đó.

Không truyền token thì script đọc biến môi trường TELEGRAM_BOT_TOKEN.
Token không được ghi vào file nào cả.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


def api(token, method, params=None):
    url = "https://api.telegram.org/bot%s/%s" % (token, method)
    data = urllib.parse.urlencode(params).encode() if params else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            return json.loads(body)
        except ValueError:
            return {"ok": False, "description": "HTTP %s: %s" % (e.code, body[:200])}


def main():
    token = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("TELEGRAM_BOT_TOKEN", "")).strip()
    if not token:
        print(__doc__)
        print("Thiếu token. Chạy:  python scripts/telegram_setup.py <TOKEN>")
        return 1

    me = api(token, "getMe")
    if not me.get("ok"):
        print("Token không dùng được: %s" % me.get("description"))
        print("Kiểm tra lại chuỗi token @BotFather đưa, dán đủ cả phần sau dấu hai chấm.")
        return 1
    bot = me["result"]
    print("Bot: @%s (%s)" % (bot.get("username"), bot.get("first_name")))

    upd = api(token, "getUpdates")
    if not upd.get("ok"):
        print("Không đọc được tin nhắn: %s" % upd.get("description"))
        return 1

    chats = {}
    for u in upd.get("result", []):
        msg = u.get("message") or u.get("edited_message") or u.get("channel_post") or {}
        ch = msg.get("chat")
        if ch:
            chats[ch["id"]] = ch

    if not chats:
        print("\nChưa thấy tin nhắn nào.")
        print("Mở Telegram, tìm @%s, bấm Start rồi nhắn một câu bất kỳ cho nó, sau đó chạy lại lệnh này."
              % bot.get("username"))
        print("(Telegram chỉ giữ tin chưa đọc khoảng 24 giờ, nên nhắn xong hãy chạy lại ngay.)")
        return 1

    print("\nTìm thấy %d cuộc trò chuyện:" % len(chats))
    for cid, ch in chats.items():
        who = ch.get("username") or " ".join(x for x in (ch.get("first_name"), ch.get("last_name")) if x) or ch.get("title")
        print("  chat id %-16s  %s  (%s)" % (cid, who, ch.get("type")))

    cid = list(chats)[0]
    r = api(token, "sendMessage", {
        "chat_id": cid,
        "text": "Bot tín hiệu đã nối xong. Từ giờ bot sẽ gửi tín hiệu vào đây sau mỗi phiên.",
    })
    if r.get("ok"):
        print("\nĐã gửi thử một tin vào chat id %s — kiểm tra Telegram xem nhận được chưa." % cid)
    else:
        print("\nGửi thử thất bại: %s" % r.get("description"))

    print("\nHai giá trị cần đặt vào GitHub (Settings → Secrets and variables → Actions):")
    print("  TELEGRAM_BOT_TOKEN = %s...%s" % (token[:10], token[-4:]))
    print("  TELEGRAM_CHAT_ID   = %s" % cid)
    print("\nChạy thử ở máy, PowerShell:")
    print('  $env:TELEGRAM_BOT_TOKEN="%s"' % token)
    print('  $env:TELEGRAM_CHAT_ID="%s"' % cid)
    print("  python scripts/signals.py --force")
    return 0


if __name__ == "__main__":
    sys.exit(main())
