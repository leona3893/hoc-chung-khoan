#!/usr/bin/env python3
"""
Tầng 1: quét một lượt cả sàn, lọc ra danh sách mã đáng xem kỹ.

Rổ quét: VNALL (toàn bộ cổ phiếu HOSE trong rổ VNAllShare) + HNX30.
UPCoM không có API nhóm công khai, và cũng là nơi screen kỹ thuật ít đáng tin nhất
vì thanh khoản quá mỏng — muốn thêm thì khai báo tay trong watchlist.json.

Hai bước:
  1. Tải lịch sử giá tất cả mã trong rổ, loại mã thanh khoản thấp
     (giá trị khớp trung bình 20 phiên dưới ngưỡng) và mã quá ít phiên.
  2. Chấm điểm bằng đúng bộ luật của fetch_ssi.analyze, ghi:
       data/scan.json            — bảng gọn cho mọi mã qua được lọc (trang web đọc)
       data/scan-shortlist.json  — danh sách mã đáng xem kỹ, fetch_ssi.py sẽ chấm lại
                                   đầy đủ (có khối ngoại, hỗ trợ/kháng cự, nến)

Điểm trong scan.json KHÔNG có thành phần khối ngoại (±10): lấy dữ liệu khối ngoại cho
342 mã là 342 request nữa, không đáng. Mã vào shortlist sẽ được chấm lại có khối ngoại.

  python scripts/scan.py                 # quét đủ, ~5 phút
  python scripts/scan.py --limit 40      # quét 40 mã đầu, để thử nhanh
  python scripts/scan.py --no-cache      # bỏ cache lịch sử, tải lại hết
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_ssi as F  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
CACHE_DIR = os.path.join(DATA_DIR, "cache", "scan-hist")
CFG_PATH = os.path.join(ROOT, "scripts", "watchlist.json")
SCAN_PATH = os.path.join(DATA_DIR, "scan.json")
SHORT_PATH = os.path.join(DATA_DIR, "scan-shortlist.json")

VN_TZ = timezone(timedelta(hours=7))

DEFAULTS = {
    "scan_groups": ["VNALL", "HNX30"],
    "scan_min_value_20d": 3_000_000_000,   # 3 tỷ đồng/phiên — dưới mức này rất khó vào ra
    "scan_min_sessions": 150,              # cần đủ phiên để MA50 và biên 52 tuần có nghĩa
    "scan_history_days": 500,
    "scan_shortlist": 40,                  # bao nhiêu mã được chấm lại đầy đủ
}


def cfg_get(cfg, key):
    return cfg.get(key, DEFAULTS[key])


# ----------------------------------------------------------------------------
def universe(groups):
    """Danh sách mã của các nhóm, kèm ảnh chụp giá hiện tại."""
    out = {}
    for g in groups:
        try:
            rows = F.get_json(F.API_GROUP.format(g))["data"] or []
        except Exception as e:  # noqa: BLE001
            print(f"[lỗi] nhóm {g}: {e}", file=sys.stderr)
            continue
        n = 0
        for r in rows:
            if r.get("stockType") != "s":
                continue
            s = r["stockSymbol"]
            if s not in out:
                out[s] = {
                    "symbol": s,
                    "name": r.get("companyNameVi") or r.get("companyNameEn") or s,
                    "exchange": (r.get("exchange") or "").upper(),
                    "groups": [],
                }
            out[s]["groups"].append(g)
            n += 1
        print(f"[nhóm] {g}: {n} mã", file=sys.stderr)
    return out


def load_hist(sym, days, use_cache=True):
    """Lịch sử giá, cache lại trong ngày để chạy lại cho nhanh."""
    p = os.path.join(CACHE_DIR, f"{sym}.json")
    today = datetime.now(VN_TZ).strftime("%Y-%m-%d")
    if use_cache and os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            if d.get("day") == today and d.get("bars"):
                return d["bars"]
        except Exception:  # noqa: BLE001
            pass
    bars = F.fetch_history(sym, days)
    # giá cổ phiếu từ API tính bằng nghìn đồng, quy về đồng
    if bars and bars[-1][4] < 1000:
        bars = [[b[0], b[1] * 1000, b[2] * 1000, b[3] * 1000, b[4] * 1000, b[5]] for b in bars]
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"symbol": sym, "day": today, "bars": bars}, f, separators=(",", ":"))
    return bars


def value20(bars):
    """Giá trị khớp trung bình 20 phiên gần nhất, tính bằng đồng."""
    seg = bars[-20:]
    if not seg:
        return 0
    return sum(b[4] * b[5] for b in seg) / len(seg)


# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="chỉ quét N mã đầu, để thử")
    ap.add_argument("--no-cache", action="store_true", help="tải lại lịch sử, bỏ cache")
    args = ap.parse_args()

    with open(CFG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    groups = cfg_get(cfg, "scan_groups")
    min_val = cfg_get(cfg, "scan_min_value_20d")
    min_ses = cfg_get(cfg, "scan_min_sessions")
    days = cfg_get(cfg, "scan_history_days")
    n_short = cfg_get(cfg, "scan_shortlist")
    bench = cfg.get("benchmark", "VNINDEX")
    keep = set(x.upper() for x in cfg.get("extra", []))

    t0 = time.time()
    meta = universe(groups)
    symbols = sorted(meta)
    if args.limit:
        symbols = symbols[:args.limit]
    print(f"Quét {len(symbols)} mã. Ngưỡng thanh khoản {min_val/1e9:.0f} tỷ/phiên.", file=sys.stderr)

    bench_bars = F.fetch_history(bench, days)
    bench_ma50 = F.sma([b[4] for b in bench_bars], 50)
    market_ok = bool(bench_ma50[-1] and bench_bars[-1][4] > bench_ma50[-1])
    print(f"[chuẩn] {bench} {bench_bars[-1][4]:,.2f} · trên MA50: {market_ok}", file=sys.stderr)

    rows, thin, short_hist, errors = [], [], [], []
    for i, s in enumerate(symbols, 1):
        try:
            bars = load_hist(s, days, use_cache=not args.no_cache)
            if len(bars) < min_ses:
                short_hist.append(s)
                continue
            v20 = value20(bars)
            if v20 < min_val:
                thin.append(s)
                continue
            summ, _ = F.analyze(s, bars, bench_bars, [], meta[s], market_ok)
            rows.append({
                "symbol": s,
                "name": meta[s]["name"],
                "exchange": meta[s]["exchange"],
                "date": summ["date"],
                "close": summ["close"],
                "chgPct": summ["chgPct"],
                "value20": round(v20),
                "volRatio": summ["volRatio"],
                "score": summ["score"],
                "rec": summ["rec"],
                "recKey": summ["recKey"],
                "trend": summ["trend"],
                "ret1m": summ["ret"]["1m"],
                "ret3m": summ["ret"]["3m"],
                "rsi": summ["ind"]["rsi"],
                "ma20": summ["ind"]["ma20"],
                "ma50": summ["ind"]["ma50"],
                "hi52": summ["ind"]["hi52"],
                "plan": summ["plan"],
                "setups": [x["key"] for x in summ.get("setups", [])],
            })
        except Exception as e:  # noqa: BLE001
            errors.append({"symbol": s, "error": str(e)[:120]})
        if i % 40 == 0:
            print(f"  …{i}/{len(symbols)} mã, {time.time()-t0:.0f}s", file=sys.stderr)

    rows.sort(key=lambda r: -r["score"])

    # Shortlist: mã điểm cao nhất, cộng các mã khai báo tay trong watchlist
    picked = [r["symbol"] for r in rows if r["recKey"] in ("buy", "acc")][:n_short]
    shortlist = sorted(set(picked) | keep)

    buckets = {}
    for r in rows:
        buckets[r["recKey"]] = buckets.get(r["recKey"], 0) + 1

    out = {
        "updatedAt": datetime.now(VN_TZ).strftime("%Y-%m-%d %H:%M"),
        "dataDate": rows[0]["date"] if rows else None,
        "source": "SSI iBoard (iboard.ssi.com.vn)",
        "groups": groups,
        "marketOk": market_ok,
        "filters": {"minValue20d": min_val, "minSessions": min_ses},
        "counts": {
            "universe": len(symbols),
            "scored": len(rows),
            "thinLiquidity": len(thin),
            "shortHistory": len(short_hist),
            "errors": len(errors),
            "byRec": buckets,
        },
        "note": ("Điểm ở bảng này chưa có thành phần khối ngoại (±10) để khỏi gọi thêm "
                 "hàng trăm request. Mã trong shortlist được chấm lại đầy đủ ở bảng điểm."),
        "shortlist": shortlist,
        "rows": rows,
        "errors": errors[:20],
    }
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SCAN_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    with open(SHORT_PATH, "w", encoding="utf-8") as f:
        json.dump({"updatedAt": out["updatedAt"], "dataDate": out["dataDate"],
                   "symbols": shortlist}, f, ensure_ascii=False, separators=(",", ":"))

    print(f"\nXong sau {time.time()-t0:.0f}s: {len(rows)} mã có điểm "
          f"({len(thin)} loại vì thanh khoản thấp, {len(short_hist)} vì quá ít phiên, "
          f"{len(errors)} lỗi).", file=sys.stderr)
    print("Phân bố: " + " · ".join(f"{k} {v}" for k, v in sorted(buckets.items(), key=lambda x: -x[1])),
          file=sys.stderr)
    print(f"Shortlist {len(shortlist)} mã: {', '.join(shortlist[:15])}"
          + (" …" if len(shortlist) > 15 else ""), file=sys.stderr)
    top = [r for r in rows if r["recKey"] in ("buy", "acc")][:10]
    if top:
        print("\nĐiểm cao nhất:", file=sys.stderr)
        for r in top:
            print(f"  {r['symbol']:<5} {r['score']:+4d}  {r['rec']:<10} "
                  f"{r['close']:>9,.0f}đ  TK {r['value20']/1e9:>5.1f} tỷ  "
                  f"3 tháng {r['ret3m'] or 0:+6.1f}%", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
