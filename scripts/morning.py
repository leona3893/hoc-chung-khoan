#!/usr/bin/env python3
"""
Tin trước giờ mở cửa: nhắc lại việc cần làm hôm nay.

Tin 16:30 nói "mã này có điểm MUA", nhưng việc đặt lệnh lại rơi vào sáng hôm sau —
qua một đêm thì dễ quên. Script này chạy khoảng 8:50, đọc lại sổ theo dõi và bảng
điểm của phiên trước rồi gửi một tin ngắn: cần đặt lệnh gì, đang giữ gì, cắt lỗ ở đâu.

KHÔNG gọi API giá, KHÔNG chấm điểm lại, KHÔNG ghi gì vào repo. Chỉ đọc hai file có
sẵn nên không bao giờ sai vì nến chưa đóng.

    python scripts/morning.py            # gửi Telegram
    python scripts/morning.py --dry      # in ra, không gửi
    python scripts/morning.py --force    # gửi cả khi không có gì để nhắc
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
ANALYSIS = os.path.join(DATA_DIR, "analysis.json")
IDEAS = os.path.join(DATA_DIR, "ideas.json")

VN_TZ = timezone(timedelta(hours=7))
GAP_SKIP = 1.04        # mở cửa cao hơn giá tín hiệu quá 4% thì bỏ, khớp với luật của ideas.py

EXIT_LABEL = {
    "stop": "chạm cắt lỗ", "target": "đạt mục tiêu", "rule": "bị hạ bậc",
    "time": "hết thời gian giữ", "gap": "bỏ vì nhảy giá",
    "adjust": "giá bị điều chỉnh cổ tức",
}


def n0(x):
    return "—" if x is None else f"{x:,.0f}".replace(",", ".")


def load(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build(analysis, ideas, today):
    pending = [i for i in (ideas.get("open") or []) if i.get("status") == "pending"]
    holding = [i for i in (ideas.get("open") or []) if i.get("status") == "open"]
    last_date = ideas.get("dataDate")
    just_closed = [c for c in (ideas.get("closed") or []) if c.get("exitDate") == last_date]

    if not (pending or holding or just_closed):
        return None, 0

    m = analysis.get("market", {}) if analysis else {}
    idx = (m.get("indices") or {}).get("VNINDEX") or {}
    lines = [f"☀️ <b>Trước giờ mở cửa · {today.strftime('%d/%m/%Y')}</b>"]
    if idx:
        lines.append(f"Phiên trước: VN-Index {idx.get('close', 0):,.2f} "
                     f"({idx.get('chgPct', 0):+.2f}%) · thị trường {esc(m.get('regime'))}")

    if pending:
        lines.append("\n<b>📌 Cần đặt lệnh hôm nay</b>")
        for it in pending:
            cap = it["signalClose"] * GAP_SKIP
            lines.append(f"• <b>{esc(it['symbol'])}</b> — mua quanh "
                         f"{n0(it.get('entryLo'))}–{n0(it.get('entryHi'))}, "
                         f"cắt lỗ {n0(it['stop'])}, mục tiêu {n0(it.get('target'))}"
                         + (f", lời/lỗ {it['rr']}:1" if it.get("rr") else ""))
            lines.append(f"  <i>Bỏ qua nếu mở cửa trên {n0(cap)} — không mua đuổi. "
                         f"Điểm {it.get('score'):+d}, {esc(it.get('rec'))}.</i>")

    if holding:
        lines.append("\n<b>🔭 Đang giữ — canh cắt lỗ</b>")
        for it in holding:
            r = it.get("openR")
            lines.append(f"• <b>{esc(it['symbol'])}</b> cắt lỗ <b>{n0(it['stop'])}</b> · "
                         f"mục tiêu {n0(it.get('target'))} · vào {n0(it.get('entryPrice'))}"
                         + (f" · đang {r:+.2f}R" if r is not None else "")
                         + f" · giữ {it.get('days', 0)} phiên")

    if just_closed:
        lines.append("\n<b>✅ Phiên trước đã đóng</b>")
        for c in just_closed:
            r = c.get("exitR")
            lines.append(f"• {esc(c['symbol'])} {EXIT_LABEL.get(c.get('exitReason'), '')} ở "
                         f"{n0(c.get('exitPrice'))}"
                         + (f" ({r:+.2f}R)" if r is not None else ""))

    lines.append("\n<i>Nhắc lại từ kế hoạch phiên " + esc(last_date) + ", không tính lại gì. "
                 "Bot không đặt lệnh — lệnh là việc của bạn.</i>")
    return "\n".join(lines), len(pending) + len(holding) + len(just_closed)


def tg_send(token, chat_id, text):
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                                   "disable_web_page_preview": "true"}).encode()
    req = urllib.request.Request("https://api.telegram.org/bot%s/sendMessage" % token,
                                 data=data, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    now = datetime.now(VN_TZ)
    if now.weekday() >= 5 and not args.force:
        print("Cuối tuần, sàn không giao dịch.", file=sys.stderr)
        return 0

    ideas = load(IDEAS)
    if not ideas:
        print("Chưa có data/ideas.json — chạy scripts/ideas.py trước.", file=sys.stderr)
        return 0
    analysis = load(ANALYSIS)

    msg, n = build(analysis, ideas, now)
    if not msg:
        print("Không có ý tưởng nào đang mở hoặc chờ khớp — không có gì để nhắc.", file=sys.stderr)
        if not args.force:
            return 0
        msg = (f"☀️ <b>Trước giờ mở cửa · {now.strftime('%d/%m/%Y')}</b>\n"
               "Sổ theo dõi đang trống: không có lệnh nào chờ đặt, không giữ mã nào. "
               "Hôm nay không có việc gì phải làm.")

    print(f"{n} mục cần nhắc.", file=sys.stderr)
    if args.dry:
        print(msg)
        return 0

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        print("Chưa có TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID — in ra thay vì gửi.", file=sys.stderr)
        print(msg)
        return 0
    try:
        r = tg_send(token, chat, msg)
        print("Đã gửi Telegram." if r.get("ok") else f"Telegram trả lỗi: {r}", file=sys.stderr)
    except urllib.error.HTTPError as e:
        print(f"Lỗi gửi Telegram: {e.code} {e.read()[:200]}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"Lỗi gửi Telegram: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
