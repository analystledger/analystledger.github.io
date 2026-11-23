"""Build the static website into docs/ (served by GitHub Pages)."""
import json
import os
import shutil
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from xml.sax.saxutils import escape

from jinja2 import Environment, FileSystemLoader, select_autoescape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ACTIONS, DATA, DOCS, ROOT, config, load_json, save_json, slugify, stance  # noqa: E402

CFG = config()
env = Environment(loader=FileSystemLoader(os.path.join(ROOT, "templates")),
                  autoescape=select_autoescape(["html", "xml"]))


def money(v):
    return f"${v:,.2f}" if isinstance(v, (int, float)) else "—"


def pct(v):
    return f"{v:+.1f}%" if isinstance(v, (int, float)) else "—"


env.filters.update(money=money, pct=pct)
env.globals.update(ACTIONS=ACTIONS, CFG=CFG, stance=stance)


def analyst_key(e):
    name = e.get("analyst") or ""
    if name:
        return slugify(f"{name}-{e['firm']}"), name
    return slugify(f"{e['firm']}-research"), f"{e['firm']} (research team)"


def directional_return(e, prices):
    s = stance(e.get("rating_to"))
    cur = (prices.get(e["ticker"]) or {}).get("price")
    start = e.get("price_at_rating")
    if s not in ("bullish", "bearish") or not cur or not start:
        return None
    r = (cur / start - 1) * 100
    return round(r if s == "bullish" else -r, 1)


def render(path, template, depth, **ctx):
    full = os.path.join(DOCS, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    html = env.get_template(template).render(root="../" * depth, page_path=path, **ctx)
    with open(full, "w", encoding="utf-8") as f:
        f.write(html)


def main():
    events = load_json(os.path.join(DATA, "events.json"), [])
    prices = load_json(os.path.join(DATA, "prices.json"), {})
    meta = load_json(os.path.join(DATA, "last_update.json"), {})
    news = sorted(load_json(os.path.join(DATA, "market_news.json"), []),
                  key=lambda n: n.get("date", ""), reverse=True)[:300]
    events.sort(key=lambda e: (e["date"], e["ticker"]), reverse=True)

    # clean generated folders (keep assets + social images)
    for sub in ("analysts", "stocks"):
        shutil.rmtree(os.path.join(DOCS, sub), ignore_errors=True)

    analysts = defaultdict(lambda: {"events": []})
    stocks = defaultdict(lambda: {"events": []})
    for e in events:
        slug, name = analyst_key(e)
        e["analyst_slug"], e["analyst_display"] = slug, name
        e["ret"] = directional_return(e, prices)
        a = analysts[slug]
        a.update(slug=slug, name=name, firm=e["firm"])
        a["events"].append(e)
        stocks[e["ticker"]]["events"].append(e)
        if e.get("company"):
            stocks[e["ticker"]]["company"] = e["company"]

    # analyst stats
    for a in analysts.values():
        ev = a["events"]
        c = Counter(x["action"] for x in ev)
        rets = [x["ret"] for x in ev if x["ret"] is not None]
        a.update(n=len(ev), upgrades=c["upgrade"], downgrades=c["downgrade"],
                 stocks=len({x["ticker"] for x in ev}), last=ev[0]["date"], first=ev[-1]["date"],
                 avg_ret=round(sum(rets) / len(rets), 1) if rets else None,
                 hit=round(100 * sum(1 for r in rets if r > 0) / len(rets)) if rets else None,
                 scored=len(rets))

    # stock consensus: latest view from each firm within 12 months
    cutoff = (date.today() - timedelta(days=365)).isoformat()
    for t, s in stocks.items():
        latest = {}
        for e in s["events"]:
            k = slugify(e["firm"])
            if e["date"] >= cutoff and k not in latest:
                latest[k] = e
        views = list(latest.values())
        st = Counter(stance(v.get("rating_to")) for v in views if v.get("rating_to"))
        pts = [v["pt_to"] for v in views if v.get("pt_to")]
        s.update(ticker=t, n=len(s["events"]), last=s["events"][0]["date"],
                 bull=st["bullish"], neutral=st["neutral"], bear=st["bearish"],
                 avg_pt=round(sum(pts) / len(pts), 2) if pts else None,
                 high_pt=max(pts) if pts else None, low_pt=min(pts) if pts else None,
                 price=(prices.get(t) or {}).get("price"), firms=len(views))
        if s["avg_pt"] and s["price"]:
            s["upside"] = round((s["avg_pt"] / s["price"] - 1) * 100, 1)

    a_list = sorted(analysts.values(), key=lambda a: (a["last"], a["n"]), reverse=True)
    s_list = sorted(stocks.values(), key=lambda s: (s["last"], s["n"]), reverse=True)
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    week = [e for e in events if e["date"] >= week_ago]
    ranked = sorted([a for a in a_list if a["scored"] >= 3], key=lambda a: a["avg_ret"], reverse=True)

    common = dict(updated=meta.get("updated_utc", ""), total=len(events),
                  n_analysts=len(a_list), n_stocks=len(s_list))
    news_by_ticker = defaultdict(list)
    for n in news:
        for t in n.get("tickers", []):
            news_by_ticker[t].append(n)
    for t, st in stocks.items():
        st["news"] = news_by_ticker.get(t, [])[:5]
    render("index.html", "index.html", 0, latest=events[:150], week=week, top_news=news[:5],
           top_stocks=sorted(s_list, key=lambda s: sum(1 for e in s["events"] if e["date"] >= week_ago),
                             reverse=True)[:10],
           ranked=ranked[:10], **common)
    render("analysts/index.html", "analysts.html", 1, analysts=a_list, **common)
    render("stocks/index.html", "stocks.html", 1, stocks=s_list, **common)
    for a in a_list:
        render(f"analysts/{a['slug']}.html", "analyst.html", 1, a=a, **common)
    for s in s_list:
        render(f"stocks/{slugify(s['ticker'])}.html", "stock.html", 1, s=s, **common)
    planner_data = {s["ticker"]: {"c": s.get("company", ""), "p": s["price"], "t": s["avg_pt"],
                                  "b": s["bull"], "n": s["neutral"], "r": s["bear"],
                                  "u": slugify(s["ticker"])} for s in s_list}
    render("planner.html", "planner.html", 0,
           stocks_json=json.dumps(planner_data, separators=(",", ":")).replace("</", "<\\/"), **common)
    render("start.html", "start.html", 0, **common)
    render("news.html", "news.html", 0, news=news, tracked=set(stocks), **common)
    render("learn.html", "learn.html", 0, **common)
    render("tools.html", "tools.html", 0, **common)
    render("journal.html", "journal.html", 0, **common)
    render("backtest.html", "backtest.html", 0, bt=load_json(os.path.join(DATA, "sigma_backtest.json"), {}), **common)
    render("about.html", "about.html", 0, **common)
    render("terms.html", "terms.html", 0, **common)
    render("privacy.html", "privacy.html", 0, **common)

    # compact search index for the client-side search box
    save_json(os.path.join(DOCS, "assets", "search.json"),
              [{"t": "a", "n": a["name"], "u": f"analysts/{a['slug']}.html"} for a in a_list] +
              [{"t": "s", "n": f"{s['ticker']} {s.get('company', '')}".strip(),
                "u": f"stocks/{slugify(s['ticker'])}.html"} for s in s_list])

    # sitemap, robots, RSS
    base = CFG["base_url"].rstrip("/") + CFG.get("base_path", "")
    urls = ["", "analysts/", "stocks/", "news.html", "learn.html", "tools.html", "backtest.html", "journal.html", "planner.html", "start.html", "about.html"] + \
           [f"analysts/{a['slug']}.html" for a in a_list] + [f"stocks/{slugify(s['ticker'])}.html" for s in s_list]
    with open(os.path.join(DOCS, "sitemap.xml"), "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
        f.writelines(f"<url><loc>{escape(base + '/' + u)}</loc></url>\n" for u in urls)
        f.write("</urlset>\n")
    with open(os.path.join(DOCS, "robots.txt"), "w") as f:
        f.write(f"User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n")
    items = []
    for e in events[:50]:
        title = f"{e['ticker']}: {e['firm']} — {ACTIONS[e['action']]}"
        if e.get("rating_to"):
            title += f" ({e['rating_to']})"
        if e.get("pt_to"):
            title += f", PT {money(e['pt_to'])}"
        items.append(f"<item><title>{escape(title)}</title><link>{base}/analysts/{e['analyst_slug']}.html</link>"
                     f"<guid isPermaLink=\"false\">{e['id']}</guid><pubDate>{e['date']}</pubDate></item>")
    with open(os.path.join(DOCS, "feed.xml"), "w") as f:
        f.write(f'<?xml version="1.0"?><rss version="2.0"><channel><title>{escape(CFG["site_name"])}</title>'
                f"<link>{base}/</link><description>{escape(CFG['tagline'])}</description>{''.join(items)}</channel></rss>")
    open(os.path.join(DOCS, ".nojekyll"), "w").close()
    print(f"Built site: {len(events)} events, {len(a_list)} analysts, {len(s_list)} stocks")


if __name__ == "__main__":
    main()
