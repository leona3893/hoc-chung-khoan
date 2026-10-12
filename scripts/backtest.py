#!/usr/bin/env python3
"""
Backtest bộ luật chấm điểm trong fetch_ssi.py — kiểm tra xem nó có kỳ vọng dương hay không.

Nguyên tắc: không nhìn trước. Điểm của ngày t chỉ dùng dữ liệu tới hết ngày t,
lệnh khớp ở GIÁ MỞ CỬA ngày t+1 (đúng như người dùng thật đọc tín hiệu sau phiên).
Có tính phí, thuế, trượt giá, T+2, lô 100 và giới hạn số vị thế mở.

Chỉ dùng thư viện chuẩn.

  python scripts/backtest.py                 # chạy đủ, dùng cache nếu có
  python scripts/backtest.py --refresh       # tải lại lịch sử giá
  python scripts/backtest.py --only HPG,FPT  # thử nhanh vài mã
  python scripts/backtest.py --years 3       # chỉ backtest 3 năm gần nhất

Đầu ra: data/backtest.json  (trang phân tích đọc file này)
Cache:  data/cache/  (không commit, xoá được)
"""

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_ssi as F  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
CACHE_DIR = os.path.join(DATA_DIR, "cache")
HIST_DIR = os.path.join(CACHE_DIR, "hist")
SCORE_DIR = os.path.join(CACHE_DIR, "scores")
CFG_PATH = os.path.join(ROOT, "scripts", "watchlist.json")
OUT_PATH = os.path.join(DATA_DIR, "backtest.json")

VN_TZ = timezone(timedelta(hours=7))

# ----------------------------------------------------------------------------
# Giả định chi phí và luật sàn — đổi ở đây nếu phí công ty chứng khoán của bạn khác
# ----------------------------------------------------------------------------
COST = {
    "feeBuy": 0.0015,      # phí mua 0,15%
    "feeSell": 0.0015,     # phí bán 0,15%
    "taxSell": 0.001,      # thuế chuyển nhượng 0,1% trên giá trị bán
    "slip": 0.0015,        # trượt giá 0,15% mỗi chiều
}
RULES = {
    "capital": 100_000_000,   # vốn khởi điểm 100 triệu
    "riskPct": 1.0,           # rủi ro mỗi lệnh = 1% vốn hiện có
    "maxPositions": 5,        # tối đa 5 vị thế mở cùng lúc
    "maxWeightPct": 25.0,     # một mã không quá 25% vốn
    "maxHoldDays": 40,        # chốt theo thời gian nếu không chạm gì
    "maxGapEntry": 4.0,       # mở cửa cao hơn giá tín hiệu > 4% thì bỏ lệnh, không mua đuổi
    "settleDays": 2,          # T+2: mua ngày t, sớm nhất bán được ngày t+2
    "lot": 100,
    "warmup": 250,            # cần 250 phiên để có MA200 và biên 52 tuần
}


# ----------------------------------------------------------------------------
# Lịch sử giá, có cache đĩa
# ----------------------------------------------------------------------------
def hist_path(sym):
    return os.path.join(HIST_DIR, f"{sym}.json")


def load_history(sym, days, refresh=False, is_index=False):
    p = hist_path(sym)
    if not refresh and os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("bars"):
            return d["bars"]
    bars = F.fetch_history(sym, days)
    if not bars:
        raise RuntimeError("không có dữ liệu giá")
    # giá cổ phiếu từ API tính bằng nghìn đồng; chỉ số thì để nguyên điểm
    if not is_index and bars[-1][4] < 1000:
        bars = [[b[0], b[1] * 1000, b[2] * 1000, b[3] * 1000, b[4] * 1000, b[5]] for b in bars]
    os.makedirs(HIST_DIR, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"symbol": sym, "fetched": datetime.now(VN_TZ).strftime("%Y-%m-%d %H:%M"), "bars": bars},
                  f, separators=(",", ":"))
    return bars


# ----------------------------------------------------------------------------
# Ma trận điểm: với mỗi mã, chấm điểm lại ở từng phiên trong quá khứ
# ----------------------------------------------------------------------------
def score_path(sym):
    return os.path.join(SCORE_DIR, f"{sym}.json")


def build_scores(sym, bars, bench_bars, bench_ma50, refresh=False):
    """Trả về dict date -> {score, recKey, stop, target, entryLo, rr}."""
    p = score_path(sym)
    if not refresh and os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("lastDate") == bars[-1][0] and d.get("n") == len(bars):
            return d["rows"]

    bench_by_date = {}
    for k, b in enumerate(bench_bars):
        bench_by_date[b[0]] = k

    rows = {}
    start = max(RULES["warmup"], 60)
    for t in range(start, len(bars)):
        d = bars[t][0]
        bk = bench_by_date.get(d)
        if bk is None:
            # mã giao dịch ngày mà chỉ số không có (rất ít) — lùi về phiên chỉ số gần nhất
            bk = max((k for dd, k in bench_by_date.items() if dd <= d), default=None)
            if bk is None:
                continue
        bslice = bench_bars[:bk + 1]
        ok = True
        ma50 = bench_ma50[bk]
        if ma50:
            ok = bslice[-1][4] > ma50
        try:
            summ, _ = F.analyze(sym, bars[:t + 1], bslice, [], {"name": sym}, ok)
        except Exception as e:  # noqa: BLE001
            print(f"  [lỗi] {sym} {d}: {e}", file=sys.stderr)
            continue
        plan = summ["plan"]
        rows[d] = {
            "score": summ["score"],
            "rec": summ["recKey"],
            "stop": plan["stop"],
            "target": plan["target"],
            "entryLo": plan["entryLo"],
            "rr": plan["rr"],
            "marketOk": ok,
        }

    os.makedirs(SCORE_DIR, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"symbol": sym, "lastDate": bars[-1][0], "n": len(bars), "rows": rows},
                  f, separators=(",", ":"))
    return rows


# ----------------------------------------------------------------------------
# Mô phỏng
# ----------------------------------------------------------------------------
def buy_price(px):
    return px * (1 + COST["slip"])


def sell_price(px):
    return px * (1 - COST["slip"])


def buy_cost(px, qty):
    v = px * qty
    return v * (1 + COST["feeBuy"])


def sell_proceeds(px, qty):
    v = px * qty
    return v * (1 - COST["feeSell"] - COST["taxSell"])


def max_drawdown(curve):
    peak, mdd, mdd_at = curve[0][1], 0.0, None
    for d, v in curve:
        if v > peak:
            peak = v
        dd = (v / peak - 1) * 100
        if dd < mdd:
            mdd, mdd_at = dd, d
    return mdd, mdd_at


def build_indicators(bars):
    """ATR14 va MA20 theo ngay — phuc vu cat lo doi va thoat theo MA20."""
    a = F.atr(bars)
    m = F.sma([b[4] for b in bars], 20)
    return {b[0]: {"atr": a[i], "ma20": m[i]} for i, b in enumerate(bars)}


def simulate(variant, calendar, bars_by_sym, scores_by_sym, ind_by_sym):
    """variant: {name, entryRecs, minRr, requireMarketOk, useTarget, targetR, trailAtr, maExit}"""
    cash = float(RULES["capital"])
    positions = {}       # sym -> dict
    pending_exit = {}    # sym -> lý do, bán ở mở cửa phiên sau
    trades = []
    curve = []
    equity_prev = cash

    entry_recs = set(variant["entryRecs"])
    min_rr = variant.get("minRr")
    need_market = variant.get("requireMarketOk", False)

    for k, day in enumerate(calendar):
        # ---------- 1. Thoát vị thế ----------
        for sym in list(positions):
            p = positions[sym]
            bar = bars_by_sym[sym].get(day)
            if not bar:
                continue
            o, h, l, c = bar[1], bar[2], bar[3], bar[4]
            held = k - p["entryK"]
            sellable = held >= RULES["settleDays"]
            if not sellable:
                continue

            exit_px = exit_reason = None
            has_target = variant.get("useTarget", True) and p["target"] is not None
            if sym in pending_exit:
                exit_px, exit_reason = sell_price(o), pending_exit.pop(sym)
            elif l <= p["stop"]:
                # hở giá xuống dưới cắt lỗ thì khớp ở mở cửa, tệ hơn mức dự tính
                exit_px, exit_reason = sell_price(min(o, p["stop"])), ("trail" if p["trailed"] else "stop")
            elif has_target and h >= p["target"]:
                exit_px, exit_reason = sell_price(max(o, p["target"])), "target"
            elif held >= RULES["maxHoldDays"]:
                exit_px, exit_reason = sell_price(c), "time"

            if exit_px is None:
                # cat lo doi theo ATR (chandelier): chi nang len, khong bao gio ha xuong
                ka = variant.get("trailAtr")
                if ka:
                    a = (ind_by_sym[sym].get(day) or {}).get("atr")
                    if a:
                        new_stop = c - ka * a
                        if new_stop > p["stop"]:
                            p["stop"] = new_stop
                            p["trailed"] = True
                # thoat khi dong cua mat MA20
                if variant.get("maExit"):
                    ma = (ind_by_sym[sym].get(day) or {}).get("ma20")
                    if ma and c < ma:
                        pending_exit[sym] = "ma20"

            if exit_px is None:
                continue
            proceeds = sell_proceeds(exit_px, p["qty"])
            cash += proceeds
            pnl = proceeds - p["cost"]
            risk_money = (p["fill"] - p["stop0"]) * p["qty"]
            trades.append({
                "symbol": sym, "entryDate": p["entryDate"], "exitDate": day,
                "entry": round(p["fill"]), "exit": round(exit_px),
                "stop": round(p["stop"]), "target": round(p["target"]) if p["target"] else None,
                "qty": p["qty"], "days": held, "reason": exit_reason,
                "pnl": round(pnl), "pnlPct": round((exit_px / p["fill"] - 1) * 100, 2),
                "r": round(pnl / risk_money, 2) if risk_money > 0 else None,
                "score": p["score"],
            })
            del positions[sym]

        # ---------- 2. Vào lệnh theo tín hiệu của phiên hôm trước ----------
        if k > 0:
            prev = calendar[k - 1]
            cands = []
            for sym, rows in scores_by_sym.items():
                if sym in positions:
                    continue
                r = rows.get(prev)
                if not r or r["rec"] not in entry_recs:
                    continue
                if min_rr is not None and (r["rr"] is None or r["rr"] < min_rr):
                    continue
                if need_market and not r["marketOk"]:
                    continue
                prev_bar = bars_by_sym[sym].get(prev)
                today_bar = bars_by_sym[sym].get(day)
                if not prev_bar or not today_bar:
                    continue
                cands.append((r["score"], sym, r, prev_bar, today_bar))
            cands.sort(key=lambda x: -x[0])

            for score, sym, r, prev_bar, today_bar in cands:
                if len(positions) >= RULES["maxPositions"]:
                    break
                o = today_bar[1]
                if (o / prev_bar[4] - 1) * 100 > RULES["maxGapEntry"]:
                    continue  # hở giá lên quá cao: không mua đuổi
                fill = buy_price(o)
                stop = r["stop"]
                if stop >= fill:
                    continue  # cắt lỗ nằm trên giá khớp thì vô nghĩa
                equity_now = cash + sum(
                    (bars_by_sym[s].get(day) or [0, 0, 0, 0, p2["fill"]])[4] * p2["qty"]
                    for s, p2 in positions.items())
                risk_money = equity_now * RULES["riskPct"] / 100
                qty = int(risk_money / (fill - stop) // RULES["lot"] * RULES["lot"])
                cap = equity_now * RULES["maxWeightPct"] / 100
                qty = min(qty, int(cap / fill // RULES["lot"] * RULES["lot"]))
                while qty > 0 and buy_cost(fill, qty) > cash:
                    qty -= RULES["lot"]
                if qty <= 0:
                    continue
                cost = buy_cost(fill, qty)
                cash -= cost
                tr = variant.get("targetR")
                target = fill + tr * (fill - stop) if tr else r["target"]
                if not variant.get("useTarget", True):
                    target = None
                positions[sym] = {
                    "qty": qty, "fill": fill, "cost": cost, "entryDate": day, "entryK": k,
                    "stop": stop, "stop0": stop, "target": target, "score": score, "trailed": False,
                }

        # ---------- 3. Tín hiệu thoát theo luật, khớp ở phiên sau ----------
        for sym, p in positions.items():
            rows = scores_by_sym.get(sym, {})
            r = rows.get(day)
            if r and r["rec"] in ("reduce", "sell"):
                pending_exit[sym] = "rule"

        # ---------- 4. Ghi đường vốn ----------
        mtm = cash
        for sym, p in positions.items():
            bar = bars_by_sym[sym].get(day)
            px = bar[4] if bar else p["fill"]
            mtm += px * p["qty"]
        curve.append((day, round(mtm)))
        equity_prev = mtm

    # thanh lý phần còn lại theo giá cuối để tính đúng tổng
    last_day = calendar[-1]
    for sym, p in list(positions.items()):
        bar = bars_by_sym[sym].get(last_day)
        px = sell_price(bar[4] if bar else p["fill"])
        proceeds = sell_proceeds(px, p["qty"])
        cash += proceeds
        risk_money = (p["fill"] - p["stop0"]) * p["qty"]
        trades.append({
            "symbol": sym, "entryDate": p["entryDate"], "exitDate": last_day,
            "entry": round(p["fill"]), "exit": round(px), "stop": round(p["stop"]),
            "target": round(p["target"]) if p["target"] else None, "qty": p["qty"], "days": len(calendar) - 1 - p["entryK"],
            "reason": "open", "pnl": round(proceeds - p["cost"]),
            "pnlPct": round((px / p["fill"] - 1) * 100, 2),
            "r": round((proceeds - p["cost"]) / risk_money, 2) if risk_money > 0 else None,
            "score": p["score"],
        })

    return metrics(variant["name"], variant.get("label", variant["name"]), trades, curve, positions)


def metrics(name, label, trades, curve, open_positions):
    start_v, end_v = curve[0][1], curve[-1][1]
    d0 = datetime.strptime(curve[0][0], "%Y-%m-%d")
    d1 = datetime.strptime(curve[-1][0], "%Y-%m-%d")
    years = max((d1 - d0).days / 365.25, 0.01)
    total_ret = (end_v / start_v - 1) * 100
    cagr = ((end_v / start_v) ** (1 / years) - 1) * 100
    mdd, mdd_at = max_drawdown(curve)

    closed = [t for t in trades if t["r"] is not None]
    wins = [t for t in closed if t["pnl"] > 0]
    losses = [t for t in closed if t["pnl"] <= 0]
    rs = [t["r"] for t in closed]
    gross_win = sum(t["pnl"] for t in wins)
    gross_loss = -sum(t["pnl"] for t in losses)
    by_reason = {}
    for t in trades:
        by_reason[t["reason"]] = by_reason.get(t["reason"], 0) + 1

    # phân rã theo năm
    per_year = {}
    for t in trades:
        y = t["exitDate"][:4]
        a = per_year.setdefault(y, {"trades": 0, "pnl": 0, "r": 0.0})
        a["trades"] += 1
        a["pnl"] += t["pnl"]
        if t["r"] is not None:
            a["r"] += t["r"]
    for y in per_year:
        per_year[y]["pnl"] = round(per_year[y]["pnl"])
        per_year[y]["r"] = round(per_year[y]["r"], 2)

    # theo mã
    per_sym = {}
    for t in trades:
        a = per_sym.setdefault(t["symbol"], {"trades": 0, "pnl": 0, "r": 0.0, "wins": 0})
        a["trades"] += 1
        a["pnl"] += t["pnl"]
        if t["pnl"] > 0:
            a["wins"] += 1
        if t["r"] is not None:
            a["r"] += t["r"]
    top = sorted(per_sym.items(), key=lambda kv: -kv[1]["pnl"])
    per_sym_out = [{"symbol": s, "trades": a["trades"], "wins": a["wins"],
                    "pnl": round(a["pnl"]), "r": round(a["r"], 2)} for s, a in top]

    return {
        "name": name, "label": label,
        "startValue": start_v, "endValue": end_v,
        "totalRetPct": round(total_ret, 2), "cagrPct": round(cagr, 2),
        "maxDdPct": round(mdd, 2), "maxDdAt": mdd_at,
        "years": round(years, 2),
        "trades": len(trades), "closed": len(closed),
        "winRatePct": round(len(wins) / len(closed) * 100, 1) if closed else None,
        "avgR": round(sum(rs) / len(rs), 3) if rs else None,
        "totalR": round(sum(rs), 2) if rs else None,
        "avgWinR": round(sum(t["r"] for t in wins) / len(wins), 2) if wins else None,
        "avgLossR": round(sum(t["r"] for t in losses) / len(losses), 2) if losses else None,
        "profitFactor": round(gross_win / gross_loss, 2) if gross_loss > 0 else None,
        "avgHoldDays": round(sum(t["days"] for t in trades) / len(trades), 1) if trades else None,
        "byReason": by_reason,
        "perYear": per_year,
        "perSymbol": per_sym_out[:12],
        "worstSymbols": per_sym_out[-5:][::-1] if len(per_sym_out) > 12 else [],
        "openAtEnd": len(open_positions),
        "curve": [{"d": d, "v": v} for d, v in curve[::max(1, len(curve) // 400)]],
        "tradeList": sorted(trades, key=lambda t: t["exitDate"], reverse=True)[:80],
    }


def buy_hold(bench_bars, calendar, label="Mua và giữ VN-Index"):
    by_date = {b[0]: b for b in bench_bars}
    first = next((by_date[d] for d in calendar if d in by_date), None)
    if not first:
        return None
    base = first[4]
    curve = []
    for d in calendar:
        b = by_date.get(d)
        if b:
            curve.append((d, round(RULES["capital"] * b[4] / base)))
        elif curve:
            curve.append((d, curve[-1][1]))
    m = metrics("benchmark", label, [], curve, {})
    return m


# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="tải lại lịch sử giá và chấm điểm lại")
    ap.add_argument("--only", help="chỉ vài mã, cách nhau bằng phẩy")
    ap.add_argument("--years", type=float, default=0, help="chỉ backtest N năm gần nhất")
    ap.add_argument("--universe", choices=["detail", "scan"], default="detail",
                    help="detail = rổ đang chấm điểm đầy đủ; scan = toàn bộ mã qua lọc thanh khoản")
    args = ap.parse_args()

    with open(CFG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    bench = cfg.get("benchmark", "VNINDEX")
    days = 2200  # ~6 năm lịch sử

    # danh sách mã: lấy đúng rổ đang được chấm điểm
    symbols = []
    if args.universe == "scan":
        scan_path = os.path.join(DATA_DIR, "scan.json")
        if not os.path.exists(scan_path):
            print("Chưa có data/scan.json — chạy scripts/scan.py trước.", file=sys.stderr)
            return 1
        with open(scan_path, encoding="utf-8") as f:
            symbols = [r["symbol"] for r in json.load(f)["rows"]]
        print(f"Rổ quét sàn: {len(symbols)} mã qua lọc thanh khoản.", file=sys.stderr)
    ana_path = os.path.join(DATA_DIR, "analysis.json")
    if not symbols and os.path.exists(ana_path):
        with open(ana_path, encoding="utf-8") as f:
            symbols = [s["symbol"] for s in json.load(f)["symbols"]]
    if not symbols:
        symbols = sorted(set(cfg.get("extra", [])))
    if args.only:
        keep = {x.strip().upper() for x in args.only.split(",")}
        symbols = [s for s in symbols if s in keep]
    print(f"Backtest {len(symbols)} mã, chuẩn so sánh {bench}.", file=sys.stderr)

    t0 = time.time()
    bench_bars = load_history(bench, days, args.refresh, is_index=True)
    bench_ma50 = F.sma([b[4] for b in bench_bars], 50)
    bench_ma50_by_date = {b[0]: bench_ma50[i] for i, b in enumerate(bench_bars)}

    bars_by_sym, scores_by_sym, ind_by_sym = {}, {}, {}
    for i, sym in enumerate(symbols, 1):
        try:
            bars = load_history(sym, days, args.refresh)
            if len(bars) < RULES["warmup"] + 30:
                print(f"  [bỏ] {sym}: chỉ {len(bars)} phiên", file=sys.stderr)
                continue
            rows = build_scores(sym, bars, bench_bars, bench_ma50, args.refresh)
            bars_by_sym[sym] = {b[0]: b for b in bars}
            ind_by_sym[sym] = build_indicators(bars)
            scores_by_sym[sym] = rows
            print(f"  [{i}/{len(symbols)}] {sym}: {len(bars)} phiên, {len(rows)} ngày có điểm "
                  f"({time.time()-t0:.0f}s)", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print(f"  [lỗi] {sym}: {e}", file=sys.stderr)

    if not scores_by_sym:
        print("Không có dữ liệu để backtest.", file=sys.stderr)
        return 1

    # lịch giao dịch = các ngày có điểm của bất kỳ mã nào
    all_days = sorted({d for rows in scores_by_sym.values() for d in rows})
    if args.years:
        cut = (datetime.now(VN_TZ) - timedelta(days=int(args.years * 365.25))).strftime("%Y-%m-%d")
        all_days = [d for d in all_days if d >= cut]
    if len(all_days) < 60:
        print("Quá ít phiên để backtest.", file=sys.stderr)
        return 1
    print(f"Giai đoạn: {all_days[0]} → {all_days[-1]} ({len(all_days)} phiên)", file=sys.stderr)

    variants = [
        {"name": "buy", "label": "Chỉ vào khi khuyến nghị MUA (điểm ≥ 45)",
         "entryRecs": ["buy"]},
        {"name": "buy_acc", "label": "Vào cả MUA và TÍCH LŨY (điểm ≥ 20)",
         "entryRecs": ["buy", "acc"]},
        {"name": "buy_rr", "label": "MUA và tỷ lệ lời/lỗ ≥ 1,5",
         "entryRecs": ["buy"], "minRr": 1.5},
        {"name": "buy_regime", "label": "MUA và VN-Index trên MA50",
         "entryRecs": ["buy"], "requireMarketOk": True},
        {"name": "buy_notarget", "label": "MUA, không chốt lời cứng (chỉ cắt lỗ và luật thoát)",
         "entryRecs": ["buy"], "useTarget": False},
        # Ba cách thoát thử nghiệm — nhằm sửa đúng chỗ yếu đã lộ ra: mục tiêu đặt ở kháng cự
        # gần nhất thường chưa tới 1R, nên thắng nhiều lệnh mà tổng vẫn không lãi.
        {"name": "buy_t2r", "label": "MUA, mục tiêu cố định 2R thay vì kháng cự gần nhất",
         "entryRecs": ["buy"], "targetR": 2.0},
        {"name": "buy_t3r", "label": "MUA, mục tiêu cố định 3R",
         "entryRecs": ["buy"], "targetR": 3.0},
        {"name": "buy_trail", "label": "MUA, không chốt lời, cắt lỗ dời theo 2,5×ATR",
         "entryRecs": ["buy"], "useTarget": False, "trailAtr": 2.5},
        {"name": "buy_ma20", "label": "MUA, thoát khi đóng cửa mất MA20",
         "entryRecs": ["buy"], "useTarget": False, "maExit": True},
        {"name": "acc_trail", "label": "MUA + TÍCH LŨY, cắt lỗ dời theo 2,5×ATR",
         "entryRecs": ["buy", "acc"], "useTarget": False, "trailAtr": 2.5},
    ]

    results = []
    for v in variants:
        r = simulate(v, all_days, bars_by_sym, scores_by_sym, ind_by_sym)
        results.append(r)
        print(f"  {v['name']:<12} {r['trades']:>4} lệnh  "
              f"thắng {r['winRatePct'] or 0:>5.1f}%  R tb {r['avgR'] if r['avgR'] is not None else 0:>6.3f}  "
              f"lãi {r['totalRetPct']:>8.2f}%  DD {r['maxDdPct']:>7.2f}%", file=sys.stderr)

    bh = buy_hold(bench_bars, all_days)
    if bh:
        results.append(bh)
        print(f"  {'benchmark':<12} {'':>4}       {'':>5}   {'':>6}        "
              f"lãi {bh['totalRetPct']:>8.2f}%  DD {bh['maxDdPct']:>7.2f}%", file=sys.stderr)

    best = max((r for r in results if r["name"] != "benchmark"),
               key=lambda r: (r["avgR"] if r["avgR"] is not None else -9, r["totalRetPct"]))

    out = {
        "updatedAt": datetime.now(VN_TZ).strftime("%Y-%m-%d %H:%M"),
        "universeKind": args.universe,
        "period": {"from": all_days[0], "to": all_days[-1], "sessions": len(all_days)},
        "universe": sorted(scores_by_sym),
        "benchmark": bench,
        "cost": COST, "rules": RULES,
        "variants": results,
        "best": best["name"],
        "caveats": [
            "Điểm trong backtest KHÔNG có thành phần khối ngoại (±10): API SSI chỉ trả dữ liệu "
            "mua/bán ròng khoảng một tháng gần nhất, không thể dựng lại cho quá khứ. Điểm thực tế "
            "trên trang phân tích có thành phần này, nên hai con số không trùng khít.",
            "Rổ cổ phiếu là VN30 hiện tại cộng vài mã thêm tay. VN30 được xét lại định kỳ, nên "
            "danh sách này chứa sẵn thiên lệch người sống sót — kết quả quá khứ bị tô hồng một phần.",
            "Lệnh giả định khớp ở giá mở cửa phiên kế tiếp cộng trượt giá; thực tế có phiên "
            "không khớp được khối lượng mong muốn, nhất là mã thanh khoản thấp.",
            "Không mô phỏng cổ tức, chia tách, quyền mua — giá lấy từ API đã điều chỉnh hay chưa "
            "là do nguồn, phần này không kiểm soát được.",
            "Kết quả quá khứ không bảo đảm tương lai. Đây là phép kiểm tra xem bộ luật có vô lý "
            "hay không, không phải lời hứa lợi nhuận.",
        ],
    }
    os.makedirs(DATA_DIR, exist_ok=True)
    out_path = OUT_PATH if args.universe == "detail" else os.path.join(DATA_DIR, "backtest-scan.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\nXong sau {time.time()-t0:.0f}s → data/backtest.json (tốt nhất theo R: {best['name']})",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
