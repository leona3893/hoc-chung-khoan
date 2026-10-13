#!/usr/bin/env python3
"""
Kiểm định độ bền của chiến lược: walk-forward và bootstrap.

Hai công cụ này KHÔNG làm chiến lược kiếm thêm tiền. Chúng trả lời câu hỏi khác:
con số dương kia là thật hay chỉ là may?

  Walk-forward:  chia lịch sử thành nhiều năm. Mỗi năm, chọn tham số tốt nhất
                 trên 2 năm TRƯỚC đó, rồi đem đúng tham số ấy chạy năm kế tiếp mà
                 không được nhìn lại. Nối các năm kiểm tra lại = kết quả ngoài mẫu.
  Bootstrap:     xáo lại các lệnh 3.000 lần để tính khoảng tin cậy 90% của lãi
                 trung bình mỗi lệnh, và xác suất nó thực sự lớn hơn 0.

    python scripts/robust.py                       # BTC + ETH
    python scripts/robust.py --symbols top10       # 10 coin lớn
"""

import argparse
import random
import sys
from datetime import datetime, timezone

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import crypto as C  # noqa: E402

TOP10 = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
         "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "LTCUSDT"]
TREND = {"slPct": None, "tpPct": None, "trailPct": None, "maxHold": None}

# Mỗi họ chiến lược kèm lưới tham số để walk-forward chọn
FAMILIES = {
    "donchian": [{"inn": a, "out": b} for a in (20, 40, 55) for b in (10, 20)],
    "ma200": [{}],
    "golden": [{}],
    "momentum": [{"look": n} for n in (60, 90, 120)],
    "donchian_btc": [{"inn": a, "out": b} for a in (20, 55) for b in (10, 20)],
}


def year_ms(y):
    return int(datetime(y, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)


def run(name, params, ctxs, cal, regime):
    st = dict(C.STRATEGIES[name])
    st["params"] = params
    return C.simulate(name, st, ctxs, cal, regime, dict(TREND))


def bootstrap(rets, n=3000, seed=7):
    if len(rets) < 5:
        return None
    rnd = random.Random(seed)
    means = sorted(sum(rnd.choice(rets) for _ in rets) / len(rets) for _ in range(n))
    return {"mean": sum(rets) / len(rets), "lo": means[int(n * 0.05)],
            "hi": means[int(n * 0.95)], "pPos": sum(1 for m in means if m > 0) / n}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="btceth")
    args = ap.parse_args()
    syms = TOP10 if args.symbols == "top10" else ["BTCUSDT", "ETHUSDT"]

    ctxs = {}
    for s in syms:
        b = C.klines(s, "1d", 96)
        if len(b) >= 400:
            ctxs[s] = C.Ctx(b)
    btc = ctxs["BTCUSDT"]
    ma = C.sma(btc.c, 200)
    regime = {btc.t[i]: ("tăng" if (ma[i] and btc.c[i] > ma[i]) else "giảm") for i in range(len(btc.t))}
    C.REGIME = regime
    cal = sorted({t for c in ctxs.values() for t in c.t})
    C.PORT.update(maxOpen=min(5, len(ctxs)), riskPct=1.0)
    y0 = datetime.fromtimestamp(cal[0] / 1000, timezone.utc).year
    y1 = datetime.fromtimestamp(cal[-1] / 1000, timezone.utc).year
    print(f"{len(ctxs)} coin, nến ngày {y0}–{y1}\n")

    print("=== WALK-FORWARD: chọn tham số trên 2 năm trước, kiểm năm sau ===")
    print("%-14s" % "chiến lược" + "".join("%9d" % y for y in range(y0 + 2, y1 + 1)) + "   năm thắng BTC")
    bh_row = {}
    for y in range(y0 + 2, y1 + 1):
        test = [t for t in cal if year_ms(y) <= t < year_ms(y + 1)]
        bh = C.buy_hold(btc, test)
        bh_row[y] = bh["totalRetPct"] if bh else 0
    oos_trades = {}
    for fam, grid in FAMILIES.items():
        row, beat, trades = "", 0, []
        for y in range(y0 + 2, y1 + 1):
            train = [t for t in cal if year_ms(y - 2) <= t < year_ms(y)]
            test = [t for t in cal if year_ms(y) <= t < year_ms(y + 1)]
            best = max(grid, key=lambda p: run(fam, p, ctxs, train, regime)["totalRetPct"])
            r = run(fam, best, ctxs, test, regime)
            trades += [t["pnlPct"] for t in r["tradeList"]]
            beat += r["totalRetPct"] > bh_row[y]
            row += "%8.0f%%" % r["totalRetPct"]
        oos_trades[fam] = trades
        print("%-14s%s   %d/%d" % (fam, row, beat, y1 - y0 - 1))
    print("%-14s%s" % ("mua giữ BTC", "".join("%8.0f%%" % bh_row[y] for y in range(y0 + 2, y1 + 1))))

    print("\n=== BOOTSTRAP: lãi trung bình mỗi lệnh ngoài mẫu, khoảng tin cậy 90% ===")
    print("%-14s %6s %9s %20s %12s" % ("chiến lược", "lệnh", "tb/lệnh", "khoảng 90%", "P(dương)"))
    for fam, rets in oos_trades.items():
        b = bootstrap(rets)
        if not b:
            print("%-14s %6d  quá ít lệnh" % (fam, len(rets)))
            continue
        print("%-14s %6d %8.2f%% %9.2f%% → %5.2f%% %11.0f%%" % (
            fam, len(rets), b["mean"], b["lo"], b["hi"], b["pPos"] * 100))
    return 0


if __name__ == "__main__":
    sys.exit(main())
