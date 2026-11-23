"""Weekly sigma-band backtest -> data/sigma_backtest.json (aggregated statistics only).

Usage:
  python3 scripts/sigma_backtest.py SPY=/path/spy.json QQQ=/path/qqq.json [--today YYYY-MM-DD]

Each input file is the JSON returned by IBKR's get_price_history (daily bars, 5 years): either the
raw object with "time" and "close" lists, or a tool-result wrapper [{"type":"text","text":"<json>"}].
Raw prices are never written to the repo; only counts and percentages are.
"""
import datetime as dt
import json
import math
import os
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "sigma_backtest.json")


def load_bars(path):
    with open(path) as f:
        d = json.load(f)
    if isinstance(d, list) and d and isinstance(d[0], dict) and "text" in d[0]:
        d = json.loads(d[0]["text"])
    return [(t[:10], c) for t, c in zip(d["time"], d["close"]) if c]


def ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def analyse(bars, today):
    bars = [b for b in bars if b[0] < today]          # drop today's unfinished bar
    days = [b[0] for b in bars]
    c = [b[1] for b in bars]
    last_of_week = {}
    for i, day in enumerate(days):
        y, w, _ = dt.date.fromisoformat(day).isocalendar()
        last_of_week[(y, w)] = i
    ends = sorted(last_of_week.values())
    rows = []
    for a, b in zip(ends, ends[1:]):
        if a < 21:
            continue
        lr = [math.log(c[j] / c[j - 1]) for j in range(a - 19, a + 1)]
        sd = st.stdev(lr) * math.sqrt(b - a)
        r = math.log(c[b] / c[a])
        rows.append(dict(end=days[b], ret=math.exp(r) - 1, z=r / sd, sig=1 - math.exp(-sd)))
    n = len(rows)
    cnt = lambda f: sum(1 for r in rows if f(r))
    below = {str(k): cnt(lambda r, k=k: r["z"] <= -k) for k in (1, 2, 3)}
    beyond = [(1 + r["ret"]) - (1 - r["sig"]) for r in rows if r["z"] <= -1]
    return dict(
        weeks=n, first=rows[0]["end"], last=rows[-1]["end"],
        stayed_above_1=n - below["1"], below=below,
        expected_below={str(k): round(n * ncdf(-k), 1) for k in (1, 2, 3)},
        above_1=cnt(lambda r: r["z"] >= 1),
        avg_band_pct=round(100 * st.mean(r["sig"] for r in rows), 2),
        avg_loss_beyond_strike_pct=round(-100 * st.mean(beyond), 2) if beyond else 0,
        worst_loss_beyond_strike_pct=round(-100 * min(beyond), 2) if beyond else 0,
        hist=[cnt(lambda r, lo=lo: lo <= r["z"] < lo + 0.5) for lo in [x / 2 for x in range(-8, 8)]],
        worst=[dict(week_ending=r["end"], move_pct=round(100 * r["ret"], 2), sigma=round(r["z"], 2))
               for r in sorted(rows, key=lambda r: r["z"])[:5]],
    )


def main():
    today = dt.date.today().isoformat()
    inputs = {}
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--today":
            today = args[i + 1]
        elif "=" in a:
            k, v = a.split("=", 1)
            inputs[k.upper()] = v
    if not inputs:
        sys.exit(__doc__)
    out = {
        "method": "Weekly close-to-close moves (last trading day of each week). One sigma = standard deviation "
                  "of the previous 20 daily moves, scaled to the trading days in the week (realised volatility, "
                  "not option-implied).",
        "source": "Computed from daily closing prices; only aggregated results are published.",
        "updated": today,
    }
    for tk, path in inputs.items():
        out[tk] = analyse(load_bars(path), today)
        d = out[tk]
        print(f"{tk}: {d['weeks']} weeks {d['first']}..{d['last']}, below -1/-2/-3 sigma = "
              f"{d['below']['1']}/{d['below']['2']}/{d['below']['3']}")
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1)
        f.write("\n")


if __name__ == "__main__":
    main()
