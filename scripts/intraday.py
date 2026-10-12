#!/usr/bin/env python3
"""
Cảnh báo trong phiên: canh giá so với các NGƯỠNG ĐÃ CỐ ĐỊNH của kế hoạch phiên trước.

Script này KHÔNG chấm điểm lại. Chấm điểm giữa phiên là chấm trên một cây nến chưa
đóng — mười giờ sáng ra MUA, hai giờ chiều ra THEO DÕI, đó là nhiễu. Ở đây chỉ so
giá khớp hiện tại với bốn mức đã tính sẵn từ phiên trước:

    mất cắt lỗ · vào vùng mua · chạm mục tiêu · giảm sàn

Mỗi ngưỡng chỉ nhắn MỘT LẦN mỗi phiên (ghi nhớ trong data/cache/, không commit).
Chỉ xét những mã phiên trước được khuyến nghị MUA hoặc TÍCH LŨY — tức những mã mà
kế hoạch giá của nó có nghĩa với bạn.

    python scripts/intraday.py            # chạy thật
    python scripts/intraday.py --dry      # in ra, không gửi, không ghi trạng thái
    python scripts/intraday.py --force    # bỏ qua kiểm tra giờ/phiên (để thử)
    python scripts/intraday.py --reset    # xoá trạng thái đã nhắn của hôm nay

Nguồn giá: iboard-query.ssi.com.vn (API công khai, giá khớp trong phiên).
Bot không đặt lệnh.
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
STATE = os.path.join(DATA_DIR, "cache", "intraday-state.json")

VN_TZ = timezone(timedelta(hours=7))
ZONE_TOL = 1.015          # "đã vào vùng mua" = giá cách mép dưới vùng không quá 1,5%
ADJ_DROP = 0.88           # rơi hơn 12% so với giá đóng cửa phiên trước = điều chỉnh giá
ACT_RECS = ("buy", "acc")  # chỉ canh mã phiên trước được khuyến nghị tích cực
OPEN_MIN = 9 * 60 + 15     # 9:15
CLOSE_MIN = 14 * 60 + 50   # 14:50, qua ATC một chút
LIVE_SESSIONS = ("ATO", "LO", "ATC", "PT", "BREAK")

KINDS = {
    "stop":   ("🔴", "mất cắt lỗ"),
    "floor":  ("🔴", "giảm sàn"),
    "entry":  ("🟢", "vào vùng mua"),
    "target": ("🟡", "chạm mục tiêu"),
    "adjust": ("⚪", "giá bị điều chỉnh"),
}


def n0(x):
    return "—" if x is None else f"{x:,.0f}".replace(",", ".")


def load(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ----------------------------------------------------------------------------
# Giá trong phiên
# ----------------------------------------------------------------------------
def fetch_live(symbols):
    """Giá khớp hiện tại của các mã. Lấy theo nhóm cho nhanh, mã lẻ thì gọi riêng."""
    want = set(symbols)
    out, session, tdate = {}, None, None

    for group in ("VN30", "HNX30"):
        if not want - set(out):
            break
        try:
            rows = F.get_json(F.API_GROUP.format(group))["data"] or []
        except Exception as e:  # noqa: BLE001
            print(f"[lỗi] nhóm {group}: {e}", file=sys.stderr)
            continue
        for r in rows:
            s = r.get("stockSymbol")
            if s in want and s not in out:
                out[s] = r
                session = session or r.get("session")
                tdate = tdate or r.get("tradingDate")

    for s in sorted(want - set(out)):
        try:
            r = F.get_json(F.API_QUOTE.format(s))["data"] or {}
            if r.get("stockSymbol"):
                out[s] = r
                session = session or r.get("session")
                tdate = tdate or r.get("tradingDate")
        except Exception as e:  # noqa: BLE001
            print(f"[lỗi] mã {s}: {e}", file=sys.stderr)

    quotes = {}
    for s, r in out.items():
        px = r.get("matchedPrice") or r.get("expectedMatchedPrice") or r.get("refPrice")
        if not px:
            continue
        quotes[s] = {
            "price": float(px),
            "chgPct": float(r.get("priceChangePercent") or 0),
            "high": float(r.get("highest") or px),
            "low": float(r.get("lowest") or px),
            "floor": float(r.get("floor") or 0),
            "ceiling": float(r.get("ceiling") or 0),
            "vol": float(r.get("stockVol") or 0),
        }
    return quotes, session, tdate


def fetch_index():
    try:
        bars = F.fetch_history("VNINDEX", 10)
        if len(bars) < 2:
            return None
        c, p = bars[-1][4], bars[-2][4]
        return {"close": c, "chgPct": (c / p - 1) * 100, "date": bars[-1][0]}
    except Exception:  # noqa: BLE001
        return None


# ----------------------------------------------------------------------------
# So ngưỡng
# ----------------------------------------------------------------------------
def check(analysis, quotes, done):
    """done: {mã: [loại đã nhắn]}. Trả về danh sách cảnh báo mới."""
    hits = []
    for s in analysis["symbols"]:
        sym = s["symbol"]
        if s["recKey"] not in ACT_RECS:
            continue
        q = quotes.get(sym)
        plan = s.get("plan") or {}
        if not q or not plan:
            continue
        px = q["price"]
        fired = set(done.get(sym, []))
        # Chuỗi giá bị điều chỉnh (cổ tức, chia tách) làm mọi ngưỡng của kế hoạch
        # phiên trước lệch hẳn. Biên độ một phiên là ±7% nên rơi hơn 12% là dấu hiệu rõ.
        if s.get("close") and px < s["close"] * ADJ_DROP:
            if "adjust" not in fired:
                icon, label = KINDS["adjust"]
                hits.append({"symbol": sym, "kind": "adjust", "icon": icon, "label": label,
                             "title": f"{sym} giá đang {n0(px)}, thấp hơn 12% so với đóng cửa "
                                      f"phiên trước {n0(s['close'])}",
                             "detail": "Vượt biên độ một phiên nên gần như chắc là điều chỉnh cổ "
                                       "tức/chia tách, không phải bị bán. Mọi ngưỡng của kế hoạch "
                                       "phiên trước đã vô nghĩa — chờ bảng điểm phiên này tính lại.",
                             "price": px, "chgPct": q["chgPct"], "rec": s["rec"]})
            continue

        def add(kind, title, detail):
            if kind in fired:
                return
            icon, label = KINDS[kind]
            hits.append({"symbol": sym, "kind": kind, "icon": icon, "label": label,
                         "title": title, "detail": detail, "price": px,
                         "chgPct": q["chgPct"], "rec": s["rec"]})

        if plan.get("stop") and px < plan["stop"]:
            add("stop",
                f"{sym} mất cắt lỗ {n0(plan['stop'])} — đang {n0(px)} ({q['chgPct']:+.2f}%)",
                "Kế hoạch phiên trước nói thoát ở mức này. Giá vẫn có thể hồi về trước khi "
                "đóng cửa, nên nếu bạn chờ xác nhận thì chờ tới ATC, đừng quyết giữa phiên vì sốt ruột.")
        if q["floor"] and px <= q["floor"]:
            add("floor",
                f"{sym} giảm sàn {n0(q['floor'])}",
                "Giảm sàn thì thường không khớp được lệnh bán. Đừng đặt kỳ vọng thoát sạch ở mức này.")
        if plan.get("entryLo") and px <= plan["entryLo"] * ZONE_TOL:
            rr = plan.get("rr")
            add("entry",
                f"{sym} vào vùng mua quanh {n0(plan['entryLo'])} — đang {n0(px)} ({q['chgPct']:+.2f}%)",
                f"Khuyến nghị phiên trước: {s['rec']}. Cắt lỗ {n0(plan.get('stop'))}, "
                f"mục tiêu {n0(plan.get('target'))}"
                + (f", lời/lỗ {rr}:1." if rr else ".")
                + ("" if (rr or 0) >= 1.5 else " Lời/lỗ dưới 1,5 — theo chính kế hoạch thì chưa đáng vào."))
        if plan.get("target") and px >= plan["target"]:
            add("target",
                f"{sym} chạm mục tiêu {n0(plan['target'])} — đang {n0(px)} ({q['chgPct']:+.2f}%)",
                "Theo kế hoạch thì chốt một phần và nâng cắt lỗ cho phần còn lại.")
    order = {"stop": 0, "floor": 1, "adjust": 2, "target": 3, "entry": 4}
    hits.sort(key=lambda h: (order[h["kind"]], h["symbol"]))
    return hits


# ----------------------------------------------------------------------------
# Telegram
# ----------------------------------------------------------------------------
def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_message(hits, idx, now, plan_date, session):
    head = f"⚡ <b>Trong phiên · {now.strftime('%H:%M')} ngày {now.strftime('%d/%m')}</b>"
    if idx:
        head += f"\nVN-Index {idx['close']:,.2f} ({idx['chgPct']:+.2f}%)"
    lines = [head, ""]
    for h in hits:
        lines.append(f"{h['icon']} {esc(h['title'])}")
        lines.append(f"  <i>{esc(h['detail'])}</i>")
    lines.append(f"\n<i>Ngưỡng lấy từ kế hoạch phiên {plan_date} — không chấm điểm lại giữa phiên. "
                 f"Nến hôm nay chưa đóng. Bot không đặt lệnh.</i>")
    return "\n".join(lines)


def tg_send(token, chat_id, text):
    data = urllib.parse.urlencode({
        "chat_id": chat_id, "text": text,
        "parse_mode": "HTML", "disable_web_page_preview": "true",
    }).encode()
    req = urllib.request.Request("https://api.telegram.org/bot%s/sendMessage" % token,
                                 data=data, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="in ra, không gửi, không ghi trạng thái")
    ap.add_argument("--force", action="store_true", help="bỏ qua kiểm tra giờ và phiên")
    ap.add_argument("--reset", action="store_true", help="xoá trạng thái đã nhắn của hôm nay")
    args = ap.parse_args()

    now = datetime.now(VN_TZ)
    today = now.strftime("%Y-%m-%d")

    if args.reset:
        if os.path.exists(STATE):
            os.remove(STATE)
            print("Đã xoá trạng thái.", file=sys.stderr)
        return 0

    minutes = now.hour * 60 + now.minute
    if not args.force:
        if now.weekday() >= 5:
            print("Cuối tuần, sàn không giao dịch.", file=sys.stderr)
            return 0
        if not (OPEN_MIN <= minutes <= CLOSE_MIN):
            print(f"Ngoài giờ giao dịch ({now.strftime('%H:%M')}), không chạy.", file=sys.stderr)
            return 0

    analysis = load(ANALYSIS)
    if not analysis:
        print("Chưa có data/analysis.json — chạy scripts/fetch_ssi.py trước.", file=sys.stderr)
        return 1
    plan_date = analysis.get("dataDate")
    watch = [s["symbol"] for s in analysis["symbols"] if s["recKey"] in ACT_RECS]
    if not watch:
        print(f"Phiên {plan_date} không có mã nào ở mức MUA/TÍCH LŨY — không có ngưỡng nào để canh.",
              file=sys.stderr)
        return 0

    quotes, session, tdate = fetch_live(watch)
    if not quotes:
        print("Không lấy được giá trong phiên.", file=sys.stderr)
        return 1
    print(f"{len(quotes)}/{len(watch)} mã có giá · phiên SSI: {session} · ngày {tdate}", file=sys.stderr)
    if not args.force and session and session not in LIVE_SESSIONS:
        print(f"Sàn không trong giờ khớp lệnh (session={session}), không chạy.", file=sys.stderr)
        return 0

    store = load(STATE, {}) or {}
    done = store.get("fired", {}) if store.get("date") == today else {}

    hits = check(analysis, quotes, done)
    print(f"{len(hits)} cảnh báo mới.", file=sys.stderr)
    for h in hits:
        print(f"  {h['kind']:<7} {h['title']}", file=sys.stderr)

    if not hits:
        return 0

    idx = fetch_index()
    msg = build_message(hits, idx, now, plan_date, session)

    if args.dry:
        print("\n--- Tin nhắn sẽ gửi ---\n", file=sys.stderr)
        print(msg)
        return 0

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        # Không có đường gửi thì in ra và KHÔNG ghi trạng thái — để khi bạn cấu hình
        # Telegram xong, cảnh báo này vẫn còn được nhắn một lần.
        print("Chưa có TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID — in ra, không ghi trạng thái.",
              file=sys.stderr)
        print(msg)
        return 0
    try:
        r = tg_send(token, chat, msg)
        if not r.get("ok"):
            print(f"Telegram trả lỗi: {r}", file=sys.stderr)
            return 1
        print("Đã gửi Telegram.", file=sys.stderr)
    except urllib.error.HTTPError as e:
        print(f"Lỗi gửi Telegram: {e.code} {e.read()[:200]}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"Lỗi gửi Telegram: {e}", file=sys.stderr)
        return 1

    # ghi nhớ đã nhắn, để lần chạy sau không nhắn lại cùng một ngưỡng
    for h in hits:
        done.setdefault(h["symbol"], []).append(h["kind"])
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump({"date": today, "updatedAt": now.strftime("%Y-%m-%d %H:%M"), "fired": done},
                  f, ensure_ascii=False, separators=(",", ":"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
