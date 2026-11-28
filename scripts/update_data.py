"""Daily data update.

Sources (each optional, used when available):
  1. Financial Modeling Prep  (env FMP_API_KEY)     - analyst grade + price-target news
     Prices for scoring: FMP if keyed, otherwise Stooq end-of-day CSV (env STOOQ_API_KEY, optional)
  2. Finnhub                  (env FINNHUB_API_KEY) - upgrade/downgrade history for watchlist
  3. data/news_events.json    - events Claude adds every day from public news reports

Everything is merged into data/events.json (the permanent history), de-duplicated,
and any *new* major changes are queued in data/alerts_pending.json for the social poster.
"""
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DATA, config, load_json, normalise, save_json, slugify, stance  # noqa: E402

CFG = config()
FMP = os.environ.get("FMP_API_KEY", "").strip()
FINNHUB = os.environ.get("FINNHUB_API_KEY", "").strip()
SESSION = requests.Session()
SESSION.headers["User-Agent"] = "AnalystLedger/1.0"
LOG = []


def log(msg):
    print(msg)
    LOG.append(msg)


def get(url, params):
    for attempt in range(3):
        try:
            r = SESSION.get(url, params=params, timeout=30)
            if r.status_code == 429:
                time.sleep(5 * (attempt + 1))
                continue
            if r.status_code != 200:
                log(f"  {url} -> HTTP {r.status_code}: {r.text[:150]}")
                return None
            return r.json()
        except (requests.RequestException, ValueError) as e:
            log(f"  {url} -> {e}")
            time.sleep(2)
    return None


# ---------------------------------------------------------------- FMP
def fetch_fmp():
    if not FMP:
        log("FMP: no FMP_API_KEY set - skipped")
        return []
    since = (date.today() - timedelta(days=CFG["fetch"]["lookback_days"])).isoformat()
    out = []
    for page in range(CFG["fetch"]["max_pages"]):
        rows = get("https://financialmodelingprep.com/stable/grades-latest-news",
                   {"page": page, "limit": 100, "apikey": FMP})
        if not isinstance(rows, list) or not rows:
            break
        for r in rows:
            out.append(normalise({
                "date": r.get("publishedDate"), "ticker": r.get("symbol"),
                "firm": r.get("gradingCompany"), "rating_from": r.get("previousGrade"),
                "rating_to": r.get("newGrade"), "action": r.get("action"),
                "price_at_rating": r.get("priceWhenPosted"), "source_url": r.get("newsURL"),
            }, "FMP"))
        if min((r.get("publishedDate") or "")[:10] for r in rows) < since:
            break
    for page in range(CFG["fetch"]["max_pages"]):
        rows = get("https://financialmodelingprep.com/stable/price-target-latest-news",
                   {"page": page, "limit": 100, "apikey": FMP})
        if not isinstance(rows, list) or not rows:
            break
        for r in rows:
            out.append(normalise({
                "date": r.get("publishedDate"), "ticker": r.get("symbol"),
                "analyst": r.get("analystName"), "firm": r.get("analystCompany") or r.get("newsPublisher"),
                "pt_to": r.get("priceTarget") or r.get("adjPriceTarget"),
                "price_at_rating": r.get("priceWhenPosted"), "source_url": r.get("newsURL"),
                "action": "reiterate",
            }, "FMP"))
        if min((r.get("publishedDate") or "")[:10] for r in rows) < since:
            break
    out = [e for e in out if e]
    log(f"FMP: {len(out)} events")
    return out


# ---------------------------------------------------------------- Finnhub
def fetch_finnhub():
    if not FINNHUB:
        log("Finnhub: no FINNHUB_API_KEY set - skipped")
        return []
    frm = (date.today() - timedelta(days=CFG["fetch"]["lookback_days"])).isoformat()
    out = []
    for t in CFG["alerts"]["watchlist"]:
        rows = get("https://finnhub.io/api/v1/stock/upgrade-downgrade",
                   {"symbol": t, "from": frm, "to": date.today().isoformat(), "token": FINNHUB})
        if not isinstance(rows, list):
            if rows is None:
                break  # endpoint not on this plan; stop hammering
            continue
        for r in rows:
            d = datetime.fromtimestamp(r.get("gradeTime", 0), tz=timezone.utc).date().isoformat()
            out.append(normalise({"date": d, "ticker": r.get("symbol"), "firm": r.get("company"),
                                  "rating_from": r.get("fromGrade"), "rating_to": r.get("toGrade"),
                                  "action": r.get("action")}, "Finnhub"))
        time.sleep(1.1)  # free tier: 60 calls/min
    out = [e for e in out if e]
    log(f"Finnhub: {len(out)} events")
    return out


# ---------------------------------------------------------------- Claude news file
def fetch_news_file():
    rows = load_json(os.path.join(DATA, "news_events.json"), [])
    out = [normalise(r, "News") for r in rows]
    out = [e for e in out if e]
    log(f"News (Claude): {len(out)} events")
    return out


# ---------------------------------------------------------------- merge
def soft_key(e):
    return (e["date"], e["ticker"], slugify(e["firm"]).split("-")[0])


def richness(e):
    return sum(1 for k in ("analyst", "rating_from", "rating_to", "pt_from", "pt_to",
                           "price_at_rating", "source_url", "company") if e.get(k))


def merge(existing, incoming):
    by_id = {e["id"]: e for e in existing}
    soft = {}
    for e in existing:
        soft.setdefault(soft_key(e), []).append(e)
    new_ids = []
    for e in incoming:
        if e["id"] in by_id:
            continue
        twins = [x for x in soft.get(soft_key(e), [])
                 if x["action"] == e["action"] or not x.get("rating_to") or not e.get("rating_to")]
        if twins:
            # same firm, same stock, same day: enrich the existing record instead of duplicating
            t = twins[0]
            for k, v in e.items():
                if v and not t.get(k):
                    t[k] = v
            if t["action"] == "reiterate" and e["action"] != "reiterate":
                t["action"] = e["action"]
            continue
        by_id[e["id"]] = e
        soft.setdefault(soft_key(e), []).append(e)
        new_ids.append(e["id"])
    return list(by_id.values()), new_ids


def fill_previous_targets(events):
    """Where a source gave only the new target, use the same firm's previous target."""
    last = {}
    for e in sorted(events, key=lambda x: x["date"]):
        k = (e["ticker"], slugify(e["firm"]))
        prev = last.get(k)
        if prev:
            if e.get("pt_to") and not e.get("pt_from") and prev.get("pt_to") and prev["pt_to"] != e["pt_to"]:
                e["pt_from"] = prev["pt_to"]
                if e["action"] == "reiterate":
                    e["action"] = "target_raise" if e["pt_to"] > prev["pt_to"] else "target_cut"
            if e.get("rating_to") and not e.get("rating_from") and prev.get("rating_to"):
                if e["action"] in ("upgrade", "downgrade"):
                    e["rating_from"] = prev["rating_to"]
        if e.get("pt_to") or e.get("rating_to"):
            last[k] = {"pt_to": e.get("pt_to") or (prev or {}).get("pt_to"),
                       "rating_to": e.get("rating_to") or (prev or {}).get("rating_to")}


# ---------------------------------------------------------------- prices (for track records)
STOOQ = os.environ.get("STOOQ_API_KEY", "").strip()


def stooq_symbol(ticker):
    """Stooq writes US tickers as e.g. nvda.us, brk-b.us."""
    return ticker.lower().replace(".", "-") + ".us"


def stooq_history(ticker, start):
    """Daily closes {YYYY-MM-DD: close} from Stooq's free CSV download, or {} on failure."""
    params = {"s": stooq_symbol(ticker), "i": "d",
              "d1": start.replace("-", ""), "d2": date.today().strftime("%Y%m%d")}
    if STOOQ:
        params["apikey"] = STOOQ
    try:
        r = SESSION.get("https://stooq.com/q/d/l/", params=params, timeout=10)
    except requests.RequestException as e:
        return {}, f"{ticker}: {e}"
    text = r.text.strip()
    if r.status_code != 200 or not text.lower().startswith("date,"):
        return {}, f"{ticker}: HTTP {r.status_code} {text[:120]!r}"
    out = {}
    for line in text.splitlines()[1:]:
        cols = line.split(",")
        try:
            out[cols[0]] = round(float(cols[4]), 2)   # Date,Open,High,Low,Close,Volume
        except (IndexError, ValueError):
            continue
    return out, None if out else f"{ticker}: empty"


def yahoo_history(ticker, start):
    """Daily split-adjusted closes {YYYY-MM-DD: close} from Yahoo Finance's public chart endpoint."""
    p1 = int(datetime.fromisoformat(start).replace(tzinfo=timezone.utc).timestamp())
    try:
        r = SESSION.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker.replace('.', '-')}",
                        params={"period1": p1, "period2": int(time.time()), "interval": "1d"},
                        headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        res = r.json()["chart"]["result"][0]
        ts, closes = res["timestamp"], res["indicators"]["quote"][0]["close"]
    except Exception as e:  # noqa: BLE001
        return {}, f"Yahoo {ticker}: {e}"
    out = {datetime.fromtimestamp(t, timezone.utc).date().isoformat(): round(c, 2) for t, c in zip(ts, closes) if c}
    return out, None if out else f"Yahoo {ticker}: empty"


def price_history(ticker, start):
    """Yahoo first (free, no key); Stooq as a fallback."""
    hist, err = yahoo_history(ticker, start)
    if hist:
        return hist, None
    hist, err2 = stooq_history(ticker, start)
    return hist, None if hist else f"{err}; {err2}"


def update_prices(events):
    """Latest close per ticker (for scoring) and the close before each rating that lacks one.

    Uses FMP when a key is set, otherwise Stooq's free end-of-day data.
    """
    prices = load_json(os.path.join(DATA, "prices.json"), {})
    today = date.today().isoformat()
    if FMP:
        tickers = sorted({e["ticker"] for e in events}, key=lambda t: prices.get(t, {}).get("date", ""))
        calls = 0
        for t in tickers:
            if prices.get(t, {}).get("checked") == today or calls >= 150:
                continue
            rows = get("https://financialmodelingprep.com/stable/quote-short", {"symbol": t, "apikey": FMP})
            calls += 1
            if isinstance(rows, list) and rows and rows[0].get("price"):
                prices[t] = {"price": round(float(rows[0]["price"]), 2), "date": today,
                             "checked": today, "source": "FMP"}
        save_json(os.path.join(DATA, "prices.json"), prices)
        log(f"Prices (FMP): refreshed {calls} tickers")
        return prices

    by_ticker = {}
    for e in events:
        by_ticker.setdefault(e["ticker"], []).append(e)
    ok, filled, errors = 0, 0, []
    for t, evs in sorted(by_ticker.items()):
        if prices.get(t, {}).get("checked") == today:
            continue
        missing = [e for e in evs if not e.get("price_at_rating")]
        start = min(e["date"] for e in missing) if missing else today
        start = (date.fromisoformat(start) - timedelta(days=10)).isoformat()
        hist, err = price_history(t, start)
        time.sleep(0.3)
        if err:
            errors.append(err)
            if not ok and len(errors) >= 5:
                log("Prices: first 5 tickers failed - skipping price update this run")
                break
            prices.setdefault(t, {})["checked"] = today
            continue
        days = sorted(hist)
        last = days[-1]
        prices[t] = {"price": hist[last], "date": last, "checked": today, "source": "Yahoo/Stooq"}
        ok += 1
        for e in missing:
            before = [d for d in days if d < e["date"]]   # close before the rating was published
            if before:
                e["price_at_rating"] = hist[before[-1]]
                filled += 1
    save_json(os.path.join(DATA, "prices.json"), prices)
    log(f"Prices: {ok} tickers updated, {filled} rating prices filled, {len(errors)} failed")
    for err in errors[:3]:
        log(f"  {err}")
    return prices


# ---------------------------------------------------------------- alerts
def major_reason(e, events_today_by_ticker):
    a = CFG["alerts"]
    big = e["ticker"] in a["watchlist"]
    if e["action"] in ("upgrade", "downgrade") and big:
        return f"{e['action']} on a major stock"
    if e["action"] in ("upgrade", "downgrade") and stance(e.get("rating_from")) and \
            {stance(e.get("rating_from")), stance(e.get("rating_to"))} == {"bullish", "bearish"}:
        return "double upgrade/downgrade"
    if e.get("pt_from") and e.get("pt_to") and big:
        chg = abs(e["pt_to"] - e["pt_from"]) / e["pt_from"] * 100
        if chg >= a["price_target_change_pct"]:
            return f"price target moved {chg:.0f}%"
    if events_today_by_ticker.get(e["ticker"], 0) >= a["cluster_actions_same_ticker"] and big:
        return "cluster of analyst actions"
    return None


def queue_alerts(events, new_ids):
    by_id = {e["id"]: e for e in events}
    recent_cut = (date.today() - timedelta(days=2)).isoformat()
    fresh = [by_id[i] for i in new_ids if by_id[i]["date"] >= recent_cut]
    counts = {}
    for e in fresh:
        counts[e["ticker"]] = counts.get(e["ticker"], 0) + 1
    pending = load_json(os.path.join(DATA, "alerts_pending.json"), [])
    seen = {p["id"] for p in pending}
    clustered = set()
    for e in fresh:
        reason = major_reason(e, counts)
        if not reason or e["id"] in seen:
            continue
        if reason == "cluster of analyst actions":
            if e["ticker"] in clustered:
                continue
            clustered.add(e["ticker"])
        pending.append({"id": e["id"], "reason": reason, "queued": date.today().isoformat()})
    save_json(os.path.join(DATA, "alerts_pending.json"), pending[-50:])
    log(f"Alerts queued: {len(pending)} pending")


def main():
    path = os.path.join(DATA, "events.json")
    existing = load_json(path, [])
    incoming = fetch_fmp() + fetch_finnhub() + fetch_news_file()
    events, new_ids = merge(existing, incoming)
    fill_previous_targets(events)
    events.sort(key=lambda e: (e["date"], e["ticker"]), reverse=True)
    update_prices(events)
    save_json(path, events)
    queue_alerts(events, new_ids)
    save_json(os.path.join(DATA, "last_update.json"), {
        "updated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "total_events": len(events), "new_events": len(new_ids), "log": LOG[-20:]})
    log(f"Done: {len(events)} total events, {len(new_ids)} new")


if __name__ == "__main__":
    main()
