"""'The hold test' carousel: what holding $10,000 of one stock since a given year really felt like.

Usage:  python scripts/hold_story.py NVDA 2015 [--out docs/social/hold]
Builds 6 portrait slides (PNG + JPEG) and a caption file from Stooq daily closes.
Price return only (split-adjusted closes), dividends/taxes/fees excluded.
"""
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(__file__))
from cards import BLUE, GREEN, MUTED, NAVY, RED, WHITE, font, logo, wrap  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from update_data import stooq_history  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W, H = 1080, 1350
NAMES = {"NVDA": "Nvidia", "AAPL": "Apple", "MSFT": "Microsoft", "AMZN": "Amazon", "TSLA": "Tesla",
         "META": "Meta", "GOOGL": "Alphabet", "NFLX": "Netflix", "AMD": "AMD", "AVGO": "Broadcom",
         "SHOP": "Shopify", "PLTR": "Palantir", "MU": "Micron", "COST": "Costco", "LLY": "Eli Lilly",
         "ADBE": "Adobe", "CRM": "Salesforce", "INTC": "Intel", "BA": "Boeing", "DIS": "Disney",
         "PYPL": "PayPal", "UBER": "Uber", "COIN": "Coinbase", "SMCI": "Super Micro", "CRWV": "CoreWeave"}
START = 10_000


def money(v):
    if v >= 1e6:
        return f"${v / 1e6:.2f} million"
    if v >= 1e4:
        return f"${round(v, -2):,.0f}"
    return f"${v:,.0f}"


def short(v):
    if v >= 1e6:
        return f"${v / 1e6:.2f}M"
    if v >= 1e3:
        return f"${v / 1e3:,.0f}K"
    return f"${v:,.0f}"


def month(d):
    return date.fromisoformat(d).strftime("%b %Y")


def drawdowns(days, vals, threshold):
    """Declines of at least `threshold` from a running peak, with trough and recovery."""
    eps, peak_i, i = [], 0, 1
    while i < len(vals):
        if vals[i] >= vals[peak_i]:
            peak_i = i
            i += 1
            continue
        # in a decline from peak_i: find the trough before a new high
        j, trough_i = i, i
        while j < len(vals) and vals[j] < vals[peak_i]:
            if vals[j] < vals[trough_i]:
                trough_i = j
            j += 1
        depth = 1 - vals[trough_i] / vals[peak_i]
        if depth >= threshold:
            eps.append({"peak": days[peak_i], "peak_v": vals[peak_i], "trough": days[trough_i],
                        "trough_v": vals[trough_i], "depth": depth,
                        "recovered": days[j] if j < len(vals) else None})
        peak_i, i = (j, j + 1) if j < len(vals) else (peak_i, j)
    return eps


def yahoo_history(ticker, start):
    """Daily split-adjusted closes from Yahoo Finance's public chart endpoint."""
    import time
    from datetime import datetime, timezone
    import requests
    p1 = int(datetime.fromisoformat(start).replace(tzinfo=timezone.utc).timestamp())
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker.replace('.', '-')}"
    try:
        r = requests.get(url, params={"period1": p1, "period2": int(time.time()), "interval": "1d",
                                      "events": "split"}, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        res = r.json()["chart"]["result"][0]
        ts, closes = res["timestamp"], res["indicators"]["quote"][0]["close"]
    except Exception as e:  # noqa: BLE001
        return {}, f"Yahoo {ticker}: {e}"
    out = {datetime.fromtimestamp(t, timezone.utc).date().isoformat(): c for t, c in zip(ts, closes) if c}
    return out, None if out else f"Yahoo {ticker}: empty"


def analyse(ticker, year):
    hist, err = yahoo_history(ticker, f"{year}-01-01")
    if err or not hist:
        hist, err = stooq_history(ticker, f"{year}-01-01")
    if err or not hist:
        raise SystemExit(f"No price data for {ticker}: {err}")
    days = sorted(d for d in hist if d >= f"{year}-01-01")
    closes = [hist[d] for d in days]
    vals = [START * c / closes[0] for c in closes]
    for thr in (0.5, 0.4, 0.3, 0.2):
        eps = drawdowns(days, vals, thr)
        if len(eps) >= 3:
            break
    eps = sorted(eps, key=lambda e: e["depth"], reverse=True)[:4]
    eps.sort(key=lambda e: e["peak"])
    # time spent below a previous high
    run, below, longest, cur = 0, 0, 0, 0
    for v in vals:
        if v >= run:
            run, cur = v, 0
        else:
            cur += 1
            longest = max(longest, cur)
        if v <= run * 0.8:
            below += 1
    years = (date.fromisoformat(days[-1]) - date.fromisoformat(days[0])).days / 365.25
    final = vals[-1]
    return {
        "ticker": ticker, "name": NAMES.get(ticker, ticker), "year": year,
        "start_day": days[0], "end_day": days[-1], "final": final,
        "multiple": final / START, "cagr": (final / START) ** (1 / years) - 1 if years > 0 else 0,
        "max_dd": max((e["depth"] for e in eps), default=0), "episodes": eps,
        "pct_below": below / len(vals), "longest_below_days": longest,
        "series": list(zip(days, vals)),
    }


# ---------- drawing helpers ----------
def base(kicker, slide, total, accent=BLUE):
    img = Image.new("RGB", (W, H), NAVY)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 14], fill=accent)
    logo(d, 70, 60, 70)
    d.text((158, 72), "Analyst Ledger", font=font(40, True), fill=WHITE)
    d.text((W - 70, 78), f"{slide}/{total}", font=font(30, True), fill=MUTED, anchor="ra")
    d.text((70, 190), kicker.upper(), font=font(30, True), fill="#7cb0ff")
    return img, d


def footer(d, text="analystledger.com"):
    d.line([70, H - 140, W - 70, H - 140], fill="#22345a", width=2)
    d.text((W // 2, H - 110), text, font=font(30, True), fill="#7cb0ff", anchor="ma")
    d.text((W // 2, H - 62), "Hypothetical. Not investment advice.", font=font(24), fill=MUTED, anchor="ma")


def para(d, y, text, size=38, fill="#dbe4f3", bold=False, gap=14, width=W - 140):
    f = font(size, bold)
    for ln in wrap(d, text, f, width):
        d.text((70, y), ln, font=f, fill=fill)
        y += size + gap
    return y


def chart(d, series, box, eps, labels=True):
    x0, y0, x1, y1 = box
    vals = [v for _, v in series]
    lo, hi = min(vals), max(vals)
    import math
    llo, lhi = math.log(lo), math.log(hi)

    def pt(i, v):
        return (x0 + (x1 - x0) * i / (len(vals) - 1), y1 - (y1 - y0) * (math.log(v) - llo) / (lhi - llo or 1))
    idx = {day: i for i, (day, _) in enumerate(series)}
    for e in eps:  # shade drawdowns
        a, b = idx[e["peak"]], idx[e["recovered"]] if e["recovered"] else len(vals) - 1
        d.rectangle([pt(a, hi)[0], y0, pt(b, hi)[0], y1], fill="#2a1b2e")
    step = max(1, len(vals) // 600)
    pts = [pt(i, vals[i]) for i in range(0, len(vals), step)] + [pt(len(vals) - 1, vals[-1])]
    d.line(pts, fill=GREEN, width=5, joint="curve")
    if labels:
        for e in eps:
            px, py = pt(idx[e["peak"]], e["peak_v"])
            tx, ty = pt(idx[e["trough"]], e["trough_v"])
            d.ellipse([tx - 9, ty - 9, tx + 9, ty + 9], fill=RED)
            d.text((tx, ty + 16), f"-{e['depth']:.0%}", font=font(28, True), fill=RED, anchor="ma")
        ex, ey = pts[-1]
        d.ellipse([ex - 10, ey - 10, ex + 10, ey + 10], fill=WHITE)
    d.text((x0, y1 + 14), str(series[0][0][:4]), font=font(26), fill=MUTED)
    d.text((x1, y1 + 14), str(series[-1][0][:4]), font=font(26), fill=MUTED, anchor="ra")


def save(img, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path, "PNG", optimize=True)
    img.convert("RGB").save(os.path.splitext(path)[0] + ".jpg", "JPEG", quality=90)


def build(a, out_dir):
    t, n, yr, eps, T = a["ticker"], a["name"], a["year"], a["episodes"], 6
    paths = []

    # 1 hook
    img, d = base("The hold test", 1, T)
    y = para(d, 270, f"$10,000 in {n} in {yr}", 64, WHITE, True)
    y = para(d, y + 6, f"= {money(a['final'])} today", 64, GREEN, True)
    y = para(d, y + 30, "Everyone quotes the ending. Almost nobody could have sat through the middle.", 40)
    chart(d, a["series"], (70, y + 60, W - 70, H - 240), eps, labels=False)
    footer(d, "Swipe to see what holding really felt like  →")
    paths.append(os.path.join(out_dir, "1.png")); save(img, paths[-1])

    # 2 the path
    img, d = base("The headline vs the ride", 2, T)
    y = para(d, 260, f"“If I'd put $10,000 into ${t} in {yr}, I'd have {money(a['final'])}.”", 46, WHITE, True)
    y = para(d, y + 20, "True. But to get there you had to watch it go:", 38)
    chain = [START]
    for e in eps:
        chain += [e["peak_v"], e["trough_v"]]
    chain.append(a["final"])
    y += 20
    for i, v in enumerate(chain):
        up = i == 0 or v >= chain[i - 1]
        col = WHITE if i == 0 else (GREEN if up else RED)
        arrow = "" if i == 0 else ("▲ " if up else "▼ ")
        d.text((110, y), arrow + short(v), font=font(50, True), fill=col)
        if i:
            chg = v / chain[i - 1] - 1
            note = (f"{chg:+.0%}" if abs(chg) < 10 else f"×{v / chain[i - 1]:.0f}")
            if i == len(chain) - 1:
                note += "  today"
            d.text((470, y + 10), note, font=font(36), fill=MUTED)
        y += 72
        if y > H - 260:
            break
    para(d, H - 230, "…and never sell.", 40, "#7cb0ff", True)
    footer(d)
    paths.append(os.path.join(out_dir, "2.png")); save(img, paths[-1])

    # 3 chart
    img, d = base(f"${t} since {yr}, value of $10,000", 3, T)
    chart(d, a["series"], (70, 270, W - 70, H - 330), eps)
    para(d, H - 290, "Red zones = stretches spent below a previous high (log scale).", 30, MUTED)
    footer(d)
    paths.append(os.path.join(out_dir, "3.png")); save(img, paths[-1])

    # 4 the worst drops
    img, d = base("The drops you had to sit through", 4, T, RED)
    y = 260
    for e in sorted(eps, key=lambda e: e["depth"], reverse=True)[:3]:
        d.text((70, y), f"-{e['depth']:.0%}", font=font(72, True), fill=RED)
        d.text((330, y + 6), f"{short(e['peak_v'])} → {short(e['trough_v'])}", font=font(44, True), fill=WHITE)
        lost = e["peak_v"] - e["trough_v"]
        rec = f"back to the high by {month(e['recovered'])}" if e["recovered"] else "still below that high today"
        d.text((330, y + 62), f"{month(e['peak'])} – {month(e['trough'])}", font=font(32), fill=MUTED)
        y = para(d, y + 110, f"{money(lost)} of paper wealth gone; {rec}.", 34) + 34
    footer(d)
    paths.append(os.path.join(out_dir, "4.png")); save(img, paths[-1])

    # 5 lesson
    img, d = base("What the chart doesn't show", 5, T)
    stats = [(f"{a['multiple']:,.0f}×" if a["multiple"] >= 10 else f"{a['multiple']:.1f}×", "total, price only"),
             (f"{a['cagr']:.0%}", "a year, compounded"),
             (f"{a['pct_below']:.0%}", "of trading days 20%+ below its peak"),
             (f"{a['longest_below_days'] / 252:.1f} yrs", "longest wait for a new high")]
    y = 260
    for big, small in stats:
        d.text((70, y), big, font=font(58, True), fill=GREEN)
        d.text((360, y + 16), small, font=font(32), fill="#dbe4f3")
        y += 92
    y = para(d, y + 30, "Big long-term winners usually come with brutal drawdowns. Hindsight makes holding look easy; living it without knowing the ending is the hard part.", 36)
    para(d, y + 20, "Size positions so you can survive the drops, and keep checking that the business still earns your conviction.", 36, WHITE, True)
    footer(d)
    paths.append(os.path.join(out_dir, "5.png")); save(img, paths[-1])

    # 6 CTA
    img, d = base("Follow Analyst Ledger", 6, T)
    y = para(d, 280, "Track every analyst call on", 50, WHITE, True)
    y = para(d, y, f"${t} and 290+ other stocks", 50, GREEN, True)
    y = para(d, y + 30, "Every upgrade, downgrade and price-target change, dated, with each analyst's track record. Free.", 38)
    d.rounded_rectangle([70, y + 50, W - 70, y + 170], radius=24, fill=BLUE)
    d.text((W // 2, y + 82), f"analystledger.com/stocks/{t.lower()}", font=font(42, True), fill=WHITE, anchor="ma")
    para(d, H - 330, f"Hypothetical $10,000 bought at the close on {a['start_day']}, valued at the close on "
         f"{a['end_day']}. Split-adjusted price return; excludes dividends, taxes and fees. "
         "Past performance does not predict future results.", 26, MUTED, gap=8)
    footer(d)
    paths.append(os.path.join(out_dir, "6.png")); save(img, paths[-1])

    worst = max(eps, key=lambda e: e["depth"]) if eps else None
    caption = (f"$10,000 in ${t} in {yr} → {money(a['final'])} today. Sounds easy. "
               + (f"It meant sitting through a {worst['depth']:.0%} drop ({money(worst['peak_v'])} → "
                  f"{money(worst['trough_v'])}) and more. " if worst else "")
               + f"Volatility is the price of long-term returns.\n\nTrack every analyst call on ${t}: "
               f"https://analystledger.com/stocks/{t.lower()}.html\n\nHypothetical, price only. Not investment advice. "
               f"#{t} #stocks #investing #longterminvesting")
    meta = {k: v for k, v in a.items() if k != "series"}
    meta.update(caption=caption, slides=[os.path.relpath(p, ROOT) for p in paths])
    with open(os.path.join(out_dir, "story.json"), "w") as f:
        json.dump(meta, f, indent=1)
    return paths, caption


if __name__ == "__main__":
    args = [x for x in sys.argv[1:] if not x.startswith("--")]
    ticker, year = args[0].upper(), int(args[1])
    out = os.path.join(ROOT, "docs", "social", "hold", f"{ticker.lower()}-{year}")
    a = analyse(ticker, year)
    paths, cap = build(a, out)
    print("\n".join(paths)); print(cap)
