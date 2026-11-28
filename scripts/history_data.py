"""Historical data for the Stocks > Historical tab.

For every tracked stock, fetches from Yahoo Finance (free, no key):
  * daily closes for the last 5 years
  * the full analyst upgrade/downgrade history (firm, grades, price targets)
  * the monthly buy/hold/sell recommendation trend

Writes:
  docs/data/hist/<ticker>.json   one file per stock, loaded by the chart on demand
  docs/data/hist/consensus.json  month-end consensus, price and action count for every stock (the table)

Usage: python scripts/history_data.py [TICKER ...]
"""
import json
import os
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DATA, DOCS, load_json, slugify, stance  # noqa: E402

OUT = os.path.join(DOCS, "data", "hist")
YEARS = 5
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}
S = requests.Session()
S.headers.update(UA)
CRUMB = None


def crumb():
    global CRUMB
    if CRUMB is None:
        try:
            S.get("https://fc.yahoo.com", timeout=15)
        except requests.RequestException:
            pass
        r = S.get("https://query2.finance.yahoo.com/v1/test/getcrumb", timeout=15)
        CRUMB = r.text.strip() if r.status_code == 200 and len(r.text) < 40 else ""
        print("Yahoo crumb:", "ok" if CRUMB else f"failed ({r.status_code})")
    return CRUMB


def ysym(t):
    return t.replace(".", "-")


def closes(t, start):
    """Split-adjusted daily closes, plus the splits [(date, ratio)] so old price targets can be adjusted too."""
    p1 = int(datetime.fromisoformat(start).replace(tzinfo=timezone.utc).timestamp())
    r = S.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{ysym(t)}",
              params={"period1": p1, "period2": int(time.time()), "interval": "1d", "events": "split"}, timeout=20)
    res = r.json()["chart"]["result"][0]
    out = {}
    for ts, c in zip(res.get("timestamp") or [], res["indicators"]["quote"][0]["close"]):
        if c:
            out[datetime.fromtimestamp(ts, timezone.utc).date().isoformat()] = round(c, 2)
    splits = [(datetime.fromtimestamp(v["date"], timezone.utc).date().isoformat(), v["numerator"] / v["denominator"])
              for v in ((res.get("events") or {}).get("splits") or {}).values() if v.get("denominator")]
    return out, splits


def adjust_targets(actions, splits):
    """Analysts' targets are quoted in the share price of their day; divide by later splits to match the chart."""
    for a in actions:
        f = 1.0
        for d, ratio in splits:
            if a[0] < d and ratio > 0:
                f *= ratio
        if f != 1.0:
            a[5] = round(a[5] / f, 2) if a[5] else a[5]
            a[6] = round(a[6] / f, 2) if a[6] else a[6]


def summary(t):
    if not crumb():
        return {}
    r = S.get(f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{ysym(t)}",
              params={"modules": "upgradeDowngradeHistory,recommendationTrend", "crumb": CRUMB}, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"quoteSummary HTTP {r.status_code}")
    return (r.json()["quoteSummary"]["result"] or [{}])[0]


ACT = {"up": "upgrade", "down": "downgrade", "init": "initiate", "main": "pt_change", "reit": "reiterate"}


def month_ends(start, end):
    out, d = [], date(start.year, start.month, 1)
    while d <= end:
        nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
        out.append(min(nxt - timedelta(days=1), end))
        d = nxt
    return out


def snapshot(actions, prices, months):
    """Per month: [bullish, neutral, bearish, avg target, close, actions that month]."""
    days = sorted(prices)
    rows = []
    for m in months:
        cut, mi = (m - timedelta(days=365)).isoformat(), m.isoformat()
        latest = {}
        for a in actions:  # newest first
            if a[0] <= mi and a[0] >= cut and a[1] not in latest:
                latest[a[1]] = a
        st = Counter(stance(a[3]) for a in latest.values() if a[3])
        pts = [a[5] for a in latest.values() if a[5]]
        px = [d for d in days if d <= mi]
        n = sum(1 for a in actions if a[0][:7] == mi[:7])
        rows.append([st["bullish"], st["neutral"], st["bearish"], round(sum(pts) / len(pts), 2) if pts else None,
                     prices[px[-1]] if px else None, n])
    return rows


def own_actions(events, t):
    """Fallback when Yahoo has no history: this site's own collected actions."""
    return [[e["date"], e["firm"], e.get("rating_from") or "", e.get("rating_to") or "", e["action"],
             e.get("pt_to"), e.get("pt_from")] for e in events if e["ticker"] == t]


def main():
    events = load_json(os.path.join(DATA, "events.json"), [])
    events.sort(key=lambda e: e["date"], reverse=True)
    tickers = [a.upper() for a in sys.argv[1:]] or sorted({e["ticker"] for e in events})
    os.makedirs(OUT, exist_ok=True)
    start = date.today().replace(year=date.today().year - YEARS)
    months = month_ends(start, date.today())
    cpath = os.path.join(OUT, "consensus.json")
    cons = load_json(cpath, {}) if sys.argv[1:] else {}
    table = cons.get("t", {})
    ok = fail = 0
    for i, t in enumerate(tickers):
        try:
            prices, splits = closes(t, (start - timedelta(days=366)).isoformat())  # lead-in year: catch its splits too
            prices = {d: v for d, v in prices.items() if d >= start.isoformat()}
        except Exception as e:  # noqa: BLE001
            prices, splits = {}, []
            print(f"{t}: prices failed: {e}")
        actions, trend = [], []
        try:
            sm = summary(t)
            for h in (sm.get("upgradeDowngradeHistory") or {}).get("history", []):
                d = datetime.fromtimestamp(h["epochGradeDate"], timezone.utc).date().isoformat()
                if d < (start - timedelta(days=366)).isoformat():  # a year of lead-in for the first consensus
                    continue
                actions.append([d, h.get("firm") or "", h.get("fromGrade") or "", h.get("toGrade") or "",
                                ACT.get(h.get("action"), h.get("action") or ""),
                                h.get("currentPriceTarget") or None, h.get("priorPriceTarget") or None])
            today = date.today().replace(day=1)
            for r in (sm.get("recommendationTrend") or {}).get("trend", []):
                k = -int((r.get("period") or "0m").rstrip("m") or 0)
                y, mth = divmod(today.month - 1 - k, 12)
                trend.append([f"{today.year + y}-{mth + 1:02d}", r.get("strongBuy", 0), r.get("buy", 0),
                              r.get("hold", 0), r.get("sell", 0), r.get("strongSell", 0)])
        except Exception as e:  # noqa: BLE001
            print(f"{t}: analyst history failed: {e}")
        adjust_targets(actions, splits)
        src = "Yahoo Finance"
        if not actions:
            actions, src = own_actions(events, t), "Analyst Ledger"
        actions.sort(key=lambda a: a[0], reverse=True)
        if not prices and not actions:
            fail += 1
            continue
        ok += 1
        with open(os.path.join(OUT, f"{slugify(t)}.json"), "w") as f:
            f.write('{"t":%s,"src":%s,"updated":%s,\n"p":[\n' % (json.dumps(t), json.dumps(src), json.dumps(date.today().isoformat())))
            f.write(",\n".join(json.dumps([d, prices[d]]) for d in sorted(prices)))
            f.write('],\n"a":[\n' + ",\n".join(json.dumps(a, ensure_ascii=False) for a in actions))
            f.write('],\n"r":' + json.dumps(sorted(trend)) + "}\n")
        table[t] = snapshot(actions, prices, months)
        if i % 25 == 0:
            print(f"{i + 1}/{len(tickers)} {t}: {len(prices)} closes, {len(actions)} actions ({src})")
        time.sleep(0.4)
    with open(cpath, "w") as f:
        json.dump({"updated": date.today().isoformat(), "months": [m.isoformat()[:7] for m in months], "t": table},
                  f, separators=(",", ":"))
    print(f"History: {ok} stocks written, {fail} failed")


if __name__ == "__main__":
    main()
