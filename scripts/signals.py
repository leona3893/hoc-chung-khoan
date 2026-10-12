#!/usr/bin/env python3
"""
Bot tín hiệu: so bảng điểm phiên mới với phiên trước, phát hiện những gì vừa ĐỔI,
ghi ra data/signals.json và (nếu có token) gửi Telegram.

Bot này KHÔNG đặt lệnh. Nó chỉ nói: mã nào vừa chuyển trạng thái, vì sao, và
kế hoạch giá kèm theo. Quyết định và lệnh là của bạn.

Chạy sau fetch_ssi.py:
    python scripts/fetch_ssi.py && python scripts/signals.py

Gửi Telegram (tuỳ chọn) — đặt hai biến môi trường:
    TELEGRAM_BOT_TOKEN   token lấy từ @BotFather
    TELEGRAM_CHAT_ID     id chat của bạn (nhắn cho bot rồi gọi getUpdates để xem)

Tuỳ chọn:
    --dry        chỉ in ra, không ghi file, không gửi
    --no-send    ghi file nhưng không gửi Telegram
    --force      gửi cả khi không có tín hiệu mới (để thử đường truyền)
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
SIGNALS = os.path.join(DATA_DIR, "signals.json")
BACKTEST = os.path.join(DATA_DIR, "backtest.json")

VN_TZ = timezone(timedelta(hours=7))
KEEP_DAYS = 45          # giữ lịch sử tín hiệu bao nhiêu ngày
KEEP_MAX = 400          # và tối đa bao nhiêu bản ghi
ZONE_TOL = 1.015        # "đã lùi về vùng mua" = giá cách mép dưới vùng không quá 1,5%

# Thứ bậc khuyến nghị, để biết nâng hay hạ bậc
RANK = {"sell": 0, "reduce": 1, "hold": 2, "acc": 3, "buy": 4}
LABEL = {"sell": "BÁN / ĐỨNG NGOÀI", "reduce": "GIẢM TỶ TRỌNG", "hold": "THEO DÕI",
         "acc": "TÍCH LŨY", "buy": "MUA"}

# Mức độ: 1 = đáng mở app xem ngay, 2 = đáng biết, 3 = ghi nhận
KIND = {
    "upgrade_buy":   (1, "MUA mới", "buy"),
    "upgrade":       (2, "Nâng bậc", "buy"),
    "downgrade_sell": (1, "Chuyển BÁN", "sell"),
    "downgrade":     (2, "Hạ bậc", "sell"),
    "entry_zone":    (2, "Về vùng mua", "buy"),
    "stop_broken":   (1, "Mất điểm cắt lỗ", "sell"),
    "target_hit":    (2, "Đạt mục tiêu", "sell"),
    "breakout":      (2, "Bứt phá", "buy"),
    "golden":        (2, "MA20 cắt lên MA50", "buy"),
    "death":         (2, "MA20 cắt xuống MA50", "sell"),
    "pullback":      (3, "Test lại MA20", "buy"),
    "volspike":      (3, "Khối lượng đột biến", "buy"),
    "regime":        (1, "Đổi trạng thái thị trường", "info"),
}


# Những loại tín hiệu gộp được thành một dòng khi có nhiều mã cùng lúc
GROUPABLE = {
    "stop_broken": "đóng cửa dưới điểm cắt lỗ của kế hoạch phiên trước",
    "target_hit": "đạt mục tiêu của kế hoạch phiên trước",
    "downgrade_sell": "chuyển sang BÁN / ĐỨNG NGOÀI",
    "downgrade": "bị hạ bậc khuyến nghị",
    "upgrade_buy": "được nâng lên MUA",
    "upgrade": "được nâng bậc khuyến nghị",
    "entry_zone": "lùi về vùng mua",
    "death": "có MA20 cắt xuống MA50",
    "golden": "có MA20 cắt lên MA50",
    "breakout": "bứt phá kèm khối lượng",
    "pullback": "test lại MA20",
    "volspike": "có khối lượng đột biến",
}


# Chỉ hai loại này có lời giải thích đúng cho mọi mã. Các loại khác (cắt MA, test MA20,
# nâng/hạ bậc) đều chứa số liệu riêng của từng mã nên dòng gộp không in giải thích.
GROUP_DETAIL_OK = {"stop_broken", "target_hit"}


def n0(x):
    return "—" if x is None else f"{x:,.0f}".replace(",", ".")


def load(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ----------------------------------------------------------------------------
# Phát hiện tín hiệu
# ----------------------------------------------------------------------------
def detect(cur, prev_state):
    """So phiên hiện tại với trạng thái đã lưu. Trả về list tín hiệu."""
    date = cur.get("dataDate")
    out = []
    prev_syms = (prev_state or {}).get("symbols", {})
    prev_market = (prev_state or {}).get("market", {})

    # --- thị trường
    regime = cur["market"].get("regime")
    if prev_market.get("regime") and prev_market["regime"] != regime:
        out.append({
            "date": date, "symbol": "VNINDEX", "name": "Toàn thị trường",
            "kind": "regime", "level": 1, "side": "info",
            "title": f"Trạng thái thị trường: {prev_market['regime']} → {regime}",
            "detail": cur["market"].get("regimeNote", ""),
            "price": None, "plan": None, "score": None, "scorePrev": None,
        })

    for s in cur["symbols"]:
        sym = s["symbol"]
        p = prev_syms.get(sym) or {}
        rec, prev_rec = s["recKey"], p.get("recKey")
        score, prev_score = s["score"], p.get("score")
        close = s["close"]
        plan = s.get("plan") or {}
        base = {
            "date": date, "symbol": sym, "name": s.get("name", sym),
            "price": close, "score": score, "scorePrev": prev_score,
            "plan": {k: plan.get(k) for k in ("entryLo", "entryHi", "stop", "target", "rr")},
        }
        top_reasons = [r["text"] for r in (s.get("reasons") or [])[:2]]

        # --- 1. Đổi bậc khuyến nghị
        if prev_rec and prev_rec != rec:
            up = RANK[rec] > RANK[prev_rec]
            if rec == "buy":
                kind = "upgrade_buy"
            elif rec in ("sell",):
                kind = "downgrade_sell"
            elif up:
                kind = "upgrade"
            else:
                kind = "downgrade"
            lvl, tag, side = KIND[kind]
            out.append(dict(base, kind=kind, level=lvl, side=side,
                            title=f"{sym}: {LABEL[prev_rec]} → {LABEL[rec]}"
                                  f" ({prev_score:+d} → {score:+d} điểm)",
                            detail=" ".join(top_reasons) or s.get("recNote", "")))

        # --- 2. Giá lùi về sát mép dưới vùng mua. entryHi luôn bằng giá đóng cửa nên
        #        "nằm trong vùng" đúng với mọi mã — phải xét khoảng cách tới entryLo.
        if rec in ("buy", "acc") and plan.get("entryLo"):
            at_support = close <= plan["entryLo"] * ZONE_TOL
            if at_support and not p.get("atZone"):
                rr = plan.get("rr")
                out.append(dict(base, kind="entry_zone", level=2 if (rr or 0) >= 1.5 else 3, side="buy",
                                title=f"{sym} lùi về vùng mua quanh {n0(plan['entryLo'])}"
                                      f" (đang {n0(close)})",
                                detail=f"Khuyến nghị {LABEL[rec]}, cắt lỗ {n0(plan.get('stop'))}, "
                                       f"mục tiêu {n0(plan.get('target'))}"
                                       + (f", lời/lỗ {rr}:1." if rr else ".")
                                       + ("" if (rr or 0) >= 1.5 else
                                          " Tỷ lệ lời/lỗ dưới 1,5 — theo chính kế hoạch thì chưa đáng vào.")))

        # --- 3. Mất điểm cắt lỗ / đạt mục tiêu của chính kế hoạch phiên trước
        pplan = p.get("plan") or {}
        if pplan.get("stop") and close < pplan["stop"] and (p.get("close") or close) >= pplan["stop"]:
            lvl, tag, side = KIND["stop_broken"]
            out.append(dict(base, kind="stop_broken", level=lvl, side=side,
                            title=f"{sym} đóng cửa dưới điểm cắt lỗ {n0(pplan['stop'])}"
                                  f" (còn {n0(close)})",
                            detail="Nếu bạn đang nắm theo kế hoạch cũ thì đây là lúc kế hoạch đó "
                                   "nói phải thoát — không phải lúc tìm lý do giữ thêm."))
        if pplan.get("target") and close >= pplan["target"] and (p.get("close") or close) < pplan["target"]:
            lvl, tag, side = KIND["target_hit"]
            out.append(dict(base, kind="target_hit", level=lvl, side=side,
                            title=f"{sym} đạt mục tiêu {n0(pplan['target'])} (đang {n0(close)})",
                            detail="Theo kế hoạch cũ thì chốt một phần và nâng cắt lỗ cho phần còn lại."))

        # --- 4. Setup kỹ thuật mới xuất hiện (chỉ báo cái vừa mới có)
        cur_setups = {x["key"]: x["text"] for x in (s.get("setups") or [])}
        prev_setups = set(p.get("setups") or [])
        for k, text in cur_setups.items():
            if k in prev_setups or k not in KIND:
                continue
            lvl, tag, side = KIND[k]
            out.append(dict(base, kind=k, level=lvl, side=side,
                            title=f"{sym}: {tag} ({LABEL.get(rec, rec)}, {score:+d} điểm)",
                            detail=text))

    order = {"buy": 0, "sell": 1, "info": 2}
    out.sort(key=lambda x: (x["level"], order.get(x["side"], 3), -(x["score"] or 0)))
    return out


def snapshot(cur):
    """Trạng thái để so với phiên sau."""
    syms = {}
    for s in cur["symbols"]:
        plan = s.get("plan") or {}
        at_zone = bool(plan.get("entryLo") and s["close"] <= plan["entryLo"] * ZONE_TOL
                       and s["recKey"] in ("buy", "acc"))
        syms[s["symbol"]] = {
            "recKey": s["recKey"], "score": s["score"], "close": s["close"],
            "plan": {k: plan.get(k) for k in ("entryLo", "entryHi", "stop", "target", "rr")},
            "setups": [x["key"] for x in (s.get("setups") or [])],
            "atZone": at_zone,
        }
    return {
        "dataDate": cur.get("dataDate"),
        "market": {"regime": cur["market"].get("regime")},
        "symbols": syms,
    }


# ----------------------------------------------------------------------------
# Telegram
# ----------------------------------------------------------------------------
def tg_send(token, chat_id, text):
    data = urllib.parse.urlencode({
        "chat_id": chat_id, "text": text,
        "parse_mode": "HTML", "disable_web_page_preview": "true",
    }).encode()
    req = urllib.request.Request("https://api.telegram.org/bot%s/sendMessage" % token,
                                 data=data, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def build_message(cur, sigs, bt, cold=False):
    m = cur["market"]
    b = m.get("breadth", {})
    lines = [
        f"<b>Phiên {esc(cur.get('dataDate'))}</b> · thị trường: {esc(m.get('regime'))}",
    ]
    idx = (m.get("indices") or {}).get("VNINDEX")
    if idx:
        lines.append(f"VN-Index {idx['close']:,.2f} ({idx['chgPct']:+.2f}%) · "
                     f"{b.get('aboveMa50', 0)}/{b.get('count', 0)} mã trên MA50")
    if cold:
        lines.append("\nĐã ghi trạng thái nền của phiên này. Từ phiên sau, bot chỉ báo những gì vừa "
                     "thay đổi so với hôm nay.")
    elif not sigs:
        lines.append("\nKhông có tín hiệu mới. Bảng điểm giữ nguyên bậc so với phiên trước.")
    else:
        now = [s for s in sigs if s["level"] == 1]
        soon = [s for s in sigs if s["level"] == 2]
        later = [s for s in sigs if s["level"] == 3]
        for title, group in (("🔴 Cần xem ngay", now), ("🟡 Đáng biết", soon), ("⚪ Ghi nhận", later)):
            if not group:
                continue
            lines.append(f"\n<b>{title}</b>")
            # Gộp các tín hiệu cùng loại: 6 mã mất cắt lỗ thì một dòng, không phải sáu dòng
            # lặp lại y nguyên lời giải thích.
            groups, order = {}, []
            for s in group:
                k = s["kind"]
                if k not in groups:
                    groups[k] = []
                    order.append(k)
                groups[k].append(s)
            shown = 0
            for k in order:
                g = groups[k]
                if len(g) >= 3 and k in GROUPABLE:
                    syms = ", ".join(x["symbol"] for x in g)
                    lines.append(f"• <b>{len(g)} mã {GROUPABLE[k]}</b>: {esc(syms)}")
                    # Chỉ in lời giải thích khi nó đúng cho cả nhóm. Lý do nâng/hạ bậc
                    # chứa số liệu riêng của từng mã nên không gộp được.
                    if k in GROUP_DETAIL_OK and g[0].get("detail"):
                        lines.append(f"  <i>{esc(g[0]['detail'][:220])}</i>")
                    shown += len(g)
                    continue
                for s in g:
                    if shown >= 9:
                        break
                    lines.append(f"• {esc(s['title'])}")
                    if s.get("detail"):
                        lines.append(f"  <i>{esc(s['detail'][:220])}</i>")
                    p = s.get("plan") or {}
                    if s["side"] == "buy" and p.get("stop"):
                        lines.append(f"  mua {n0(p.get('entryLo'))}–{n0(p.get('entryHi'))} · "
                                     f"cắt lỗ {n0(p.get('stop'))} · mục tiêu {n0(p.get('target'))}"
                                     + (f" · {p['rr']}:1" if p.get("rr") else ""))
                    shown += 1
            if shown < len(group):
                lines.append(f"  …và {len(group) - shown} tín hiệu nữa, xem trên trang phân tích.")

    if bt:
        v = next((x for x in bt["variants"] if x["name"] == bt.get("best")), None)
        if v and v.get("avgR") is not None:
            lines.append(f"\n<i>Backtest bộ luật này ({bt['period']['from']}→{bt['period']['to']}): "
                         f"R trung bình {v['avgR']:+.3f}/lệnh, thắng {v['winRatePct']}%. "
                         f"Tín hiệu là gợi ý để bạn tự kiểm tra, không phải lệnh mua.</i>")
    lines.append("\nKhông phải khuyến nghị đầu tư. Bot không đặt lệnh.")
    return "\n".join(lines)


# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--no-send", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    cur = load(ANALYSIS)
    if not cur:
        print("Chưa có data/analysis.json — chạy scripts/fetch_ssi.py trước.", file=sys.stderr)
        return 1
    store = load(SIGNALS, {"state": None, "history": []}) or {"state": None, "history": []}
    cold_start = False
    prev_state = store.get("state")
    bt = load(BACKTEST)

    if prev_state and prev_state.get("dataDate") == cur.get("dataDate") and not args.force:
        print(f"Phiên {cur.get('dataDate')} đã xử lý rồi, không có gì mới.", file=sys.stderr)
        sigs = [h for h in store.get("history", []) if h["date"] == cur.get("dataDate")]
        same_day = True
    elif not prev_state:
        # Lần chạy đầu chưa có gì để so: mọi setup đang có đều là chuyện cũ.
        # Chỉ ghi trạng thái nền, từ phiên sau mới có tín hiệu thật.
        sigs, same_day, cold_start = [], False, True
        print("Lần chạy đầu: ghi trạng thái nền cho phiên này, chưa phát tín hiệu.", file=sys.stderr)
    else:
        sigs = detect(cur, prev_state)
        same_day = False

    lvl1 = sum(1 for s in sigs if s["level"] == 1)
    print(f"Phiên {cur.get('dataDate')}: {len(sigs)} tín hiệu ({lvl1} mức ưu tiên cao).", file=sys.stderr)
    for s in sigs[:12]:
        print(f"  [{s['level']}] {s['title']}", file=sys.stderr)

    if args.dry:
        print("\n--- Tin nhắn Telegram sẽ gửi ---\n", file=sys.stderr)
        print(build_message(cur, sigs, bt, cold_start))
        return 0

    if not same_day:
        hist = sigs + store.get("history", [])
        cutoff = (datetime.now(VN_TZ) - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
        hist = [h for h in hist if (h.get("date") or "") >= cutoff][:KEEP_MAX]
        out = {
            "updatedAt": datetime.now(VN_TZ).strftime("%Y-%m-%d %H:%M"),
            "dataDate": cur.get("dataDate"),
            "counts": {"total": len(sigs), "level1": lvl1,
                       "buy": sum(1 for s in sigs if s["side"] == "buy"),
                       "sell": sum(1 for s in sigs if s["side"] == "sell")},
            "latest": sigs,
            "history": hist,
            "state": snapshot(cur),
        }
        with open(SIGNALS, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
        print(f"Đã ghi data/signals.json ({len(hist)} bản ghi trong {KEEP_DAYS} ngày).", file=sys.stderr)

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if args.no_send:
        print("Bỏ qua gửi Telegram (--no-send).", file=sys.stderr)
        return 0
    if not token or not chat:
        print("Chưa có TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID — chỉ ghi file.", file=sys.stderr)
        return 0
    if not sigs and not cold_start and not args.force:
        print("Không có tín hiệu mới nên không gửi tin.", file=sys.stderr)
        return 0
    try:
        r = tg_send(token, chat, build_message(cur, sigs, bt, cold_start))
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
