"""Automatic social posting.

Usage:
  python scripts/post_social.py alerts   # post queued major changes (data/alerts_pending.json)
  python scripts/post_social.py weekly   # weekly recap of analyst actions
  python scripts/post_social.py queue    # posts Claude prepared in data/posts_queue.json (e.g. weekly options ideas)
  add --dry-run to print without posting.

Each platform is used only when its secrets are set, and a failure on one platform never blocks the others.
Secrets (GitHub > Settings > Secrets and variables > Actions):
  X:          X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET
  Bluesky:    BSKY_HANDLE, BSKY_APP_PASSWORD
  Mastodon:   MASTODON_INSTANCE (e.g. https://mastodon.social), MASTODON_TOKEN
  Telegram:   TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (e.g. @analystledger)
  Facebook:   FB_PAGE_ID, FB_PAGE_TOKEN
  Instagram:  IG_USER_ID (+ FB_PAGE_TOKEN)
  TikTok:     TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, TIKTOK_REFRESH_TOKEN
"""
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cards import GREEN, RED, card  # noqa: E402
from common import ACTIONS, DATA, DOCS, config, load_json, save_json, slugify  # noqa: E402

CFG = config()
SITE = CFG["base_url"].rstrip("/") + CFG.get("base_path", "")
DRY = "--dry-run" in sys.argv
ENV = os.environ.get
GRAPH = "https://graph.facebook.com/v21.0"


def money(v):
    return f"${v:,.2f}".replace(".00", "") if v else ""


# ------------------------------------------------------------------ content builders
def describe(e):
    who = f"{e['firm']} ({e['analyst']})" if e.get("analyst") else e["firm"]
    verb = {"upgrade": "upgrades", "downgrade": "downgrades", "initiate": "starts coverage of",
            "reiterate": "reiterates on", "target_raise": "raises target on", "target_cut": "cuts target on",
            "terminate": "drops coverage of"}[e["action"]]
    s = f"{who} {verb} ${e['ticker']}"
    if e.get("rating_to"):
        s += f" to {e['rating_to']}" if e["action"] in ("upgrade", "downgrade", "initiate") else f" — {e['rating_to']}"
        if e.get("rating_from") and e["action"] in ("upgrade", "downgrade"):
            s += f" from {e['rating_from']}"
    if e.get("pt_to"):
        s += f"; PT {money(e['pt_from']) + ' → ' if e.get('pt_from') and e['pt_from'] != e['pt_to'] else ''}{money(e['pt_to'])}"
    return s + "."


def analyst_url(e):
    slug = slugify(f"{e['analyst']}-{e['firm']}") if e.get("analyst") else slugify(f"{e['firm']}-research")
    return f"{SITE}/analysts/{slug}.html"


def alert_post(e, reason):
    icon = {"upgrade": "🟢", "downgrade": "🔴", "target_raise": "📈", "target_cut": "📉"}.get(e["action"], "🔔")
    body = describe(e)
    url = analyst_url(e)
    tags = f"#{re.sub(r'[^A-Za-z]', '', e['ticker'])} " + " ".join(CFG["hashtags"][:2])
    short = f"{icon} {ACTIONS[e['action']]}: {body}\n\nFull analyst history: {url}\n{CFG['post_disclaimer']} {tags}"
    long = (f"{icon} {ACTIONS[e['action']].upper()} — ${e['ticker']}{' (' + e['company'] + ')' if e.get('company') else ''}\n\n"
            f"{body}\nDate: {e['date']}\n\nWhy we flagged it: {reason}.\n\n"
            f"See every dated call this analyst has made and how they scored: {url}\n\n"
            f"{CFG['post_disclaimer']} {tags} " + " ".join(CFG["hashtags"][2:]))
    col = GREEN if e["action"] in ("upgrade", "target_raise") else RED if e["action"] in ("downgrade", "target_cut") else None
    lines = [(f"{e['firm']}" + (f" · {e['analyst']}" if e.get("analyst") else ""), None)]
    if e.get("rating_to"):
        lines.append(((f"{e['rating_from']} → " if e.get("rating_from") else "") + e["rating_to"], col))
    if e.get("pt_to"):
        lines.append((f"Price target: {(money(e['pt_from']) + ' → ') if e.get('pt_from') else ''}{money(e['pt_to'])}", None))
    lines.append((f"Date: {e['date']}", "#9fb0cc"))
    img = card(os.path.join(DOCS, "social", f"alert-{e['id']}.png"), f"{ACTIONS[e['action']]} alert",
               f"${e['ticker']}" + (f" · {e['company']}" if e.get("company") else ""), lines,
               "Full history at " + SITE.replace("https://", ""), accent=col)
    return {"id": f"alert-{e['id']}", "short": short, "long": long, "image": img, "title": f"{ACTIONS[e['action']]}: ${e['ticker']}"}


def weekly_post(events):
    end = date.today()
    start = end - timedelta(days=7)
    wk = [e for e in events if start.isoformat() < e["date"] <= end.isoformat()]
    if not wk:
        return None
    ups = [e for e in wk if e["action"] == "upgrade"]
    downs = [e for e in wk if e["action"] == "downgrade"]
    cover = {}
    for e in wk:
        cover[e["ticker"]] = cover.get(e["ticker"], 0) + 1
    hot = sorted(cover.items(), key=lambda x: -x[1])[:3]
    hot_txt = ", ".join(f"${t} ({n})" for t, n in hot)
    short = (f"📊 Week in analyst ratings ({start + timedelta(days=1):%b %d}–{end:%b %d})\n"
             f"{len(wk)} changes · {len(ups)} upgrades · {len(downs)} downgrades\n"
             f"Most covered: {hot_txt}\n{SITE}\n{CFG['post_disclaimer']} #stocks")
    if len(short) > 275:
        short = short.replace(f"Most covered: {hot_txt}\n", "")
    top_up = "\n".join("• " + describe(e) for e in ups[:4]) or "• none"
    top_dn = "\n".join("• " + describe(e) for e in downs[:4]) or "• none"
    long = (f"📊 WEEKLY ANALYST RECAP — {start + timedelta(days=1):%b %d} to {end:%b %d}, {end:%Y}\n\n"
            f"{len(wk)} rating changes tracked: {len(ups)} upgrades, {len(downs)} downgrades.\n"
            f"Most covered: {hot_txt}\n\nNotable upgrades:\n{top_up}\n\nNotable downgrades:\n{top_dn}\n\n"
            f"Every call, dated, with each analyst's track record: {SITE}\n\n"
            f"{CFG['post_disclaimer']} " + " ".join(CFG["hashtags"]))
    lines = [(f"{len(wk)} rating changes", None), (f"▲ {len(ups)} upgrades", GREEN), (f"▼ {len(downs)} downgrades", RED),
             (f"Most covered: {hot_txt}", None)]
    for e in (ups[:2] + downs[:2]):
        lines.append((f"{'▲' if e['action'] == 'upgrade' else '▼'} ${e['ticker']} — {e['firm']}: {e.get('rating_to', '')}", "#dbe4f3"))
    pid = f"weekly-{end.isoformat()}"
    img = card(os.path.join(DOCS, "social", f"{pid}.png"), "Weekly recap",
               f"Wall Street's week: {start + timedelta(days=1):%b %d} – {end:%b %d}", lines,
               "Full histories at " + SITE.replace("https://", ""))
    return {"id": pid, "short": short, "long": long, "image": img, "title": "Weekly analyst recap"}


def queued_posts():
    q = load_json(os.path.join(DATA, "posts_queue.json"), [])
    out = []
    for p in q:
        if p.get("status") != "pending":
            continue
        if p.get("not_before") and p["not_before"] > datetime.now(timezone.utc).isoformat():
            continue
        img = card(os.path.join(DOCS, "social", f"{p['id']}.png"), p.get("kicker", "Options watch"), p["title"],
                   [(ln, None) for ln in p.get("card_lines", [])], "More at " + SITE.replace("https://", ""))
        short = p["short"].strip()
        if CFG["post_disclaimer"] not in short:
            short += f"\n{CFG['post_disclaimer']}"
        long = p.get("long", p["short"]).strip()
        if CFG["post_disclaimer"] not in long:
            long += f"\n\n{CFG['post_disclaimer']}"
        out.append({"id": p["id"], "short": short, "long": long, "image": img, "title": p["title"]})
    return out


# ------------------------------------------------------------------ platforms
def public_image_url(post, ext=None):
    path = os.path.splitext(post["image"])[0] + ext if ext else post["image"]
    rel = os.path.relpath(path, DOCS).replace(os.sep, "/")
    url = f"{SITE}/{rel}"
    if DRY:
        return url
    for _ in range(40):  # wait for GitHub Pages to publish the image (max ~10 min)
        try:
            if requests.head(url, timeout=15).status_code == 200:
                return url
        except requests.RequestException:
            pass
        time.sleep(15)
    raise RuntimeError(f"image not live yet: {url}")


def post_x(p):
    from requests_oauthlib import OAuth1
    auth = OAuth1(ENV("X_API_KEY"), ENV("X_API_SECRET"), ENV("X_ACCESS_TOKEN"), ENV("X_ACCESS_SECRET"))
    text = p["short"] if len(p["short"]) <= 280 else p["short"][:276] + "…"
    r = requests.post("https://api.twitter.com/2/tweets", json={"text": text}, auth=auth, timeout=30)
    r.raise_for_status()


def post_bluesky(p):
    base = "https://bsky.social/xrpc"
    s = requests.post(f"{base}/com.atproto.server.createSession",
                      json={"identifier": ENV("BSKY_HANDLE"), "password": ENV("BSKY_APP_PASSWORD")}, timeout=30)
    s.raise_for_status()
    s = s.json()
    h = {"Authorization": f"Bearer {s['accessJwt']}"}
    text = p["short"]
    while len(text) > 300:
        text = text[:297] + "…"
    with open(p["image"], "rb") as f:
        blob = requests.post(f"{base}/com.atproto.repo.uploadBlob", data=f.read(),
                             headers={**h, "Content-Type": "image/png"}, timeout=60)
    blob.raise_for_status()
    facets = []
    b = text.encode("utf-8")
    for m in re.finditer(rb"https?://[^\s]+", b):
        facets.append({"index": {"byteStart": m.start(), "byteEnd": m.end()},
                       "features": [{"$type": "app.bsky.richtext.facet#link", "uri": m.group().decode()}]})
    for m in re.finditer(rb"(?<!\S)#([A-Za-z][A-Za-z0-9_]*)", b):
        facets.append({"index": {"byteStart": m.start(), "byteEnd": m.end()},
                       "features": [{"$type": "app.bsky.richtext.facet#tag", "tag": m.group(1).decode()}]})
    record = {"$type": "app.bsky.feed.post", "text": text, "facets": facets,
              "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
              "embed": {"$type": "app.bsky.embed.images",
                        "images": [{"alt": p["title"], "image": blob.json()["blob"]}]}}
    r = requests.post(f"{base}/com.atproto.repo.createRecord", headers=h, timeout=30,
                      json={"repo": s["did"], "collection": "app.bsky.feed.post", "record": record})
    r.raise_for_status()


def post_mastodon(p):
    inst, h = ENV("MASTODON_INSTANCE").rstrip("/"), {"Authorization": f"Bearer {ENV('MASTODON_TOKEN')}"}
    with open(p["image"], "rb") as f:
        m = requests.post(f"{inst}/api/v2/media", headers=h, files={"file": f},
                          data={"description": p["title"]}, timeout=60)
    m.raise_for_status()
    text = p["long"][:495]
    r = requests.post(f"{inst}/api/v1/statuses", headers=h, timeout=30,
                      data={"status": text, "media_ids[]": m.json()["id"], "visibility": "public"})
    r.raise_for_status()


def post_telegram(p):
    tok, chat = ENV("TELEGRAM_BOT_TOKEN"), ENV("TELEGRAM_CHAT_ID")
    cap = p["long"] if len(p["long"]) <= 1024 else p["long"][:1020] + "…"
    with open(p["image"], "rb") as f:
        r = requests.post(f"https://api.telegram.org/bot{tok}/sendPhoto", timeout=60,
                          data={"chat_id": chat, "caption": cap}, files={"photo": f})
    r.raise_for_status()


def page_token():
    """FB_PAGE_TOKEN may hold either the Page token or the long-lived user token; return a Page token."""
    tok = ENV("FB_PAGE_TOKEN")
    try:
        r = requests.get(f"{GRAPH}/{ENV('FB_PAGE_ID')}", params={"fields": "access_token", "access_token": tok},
                         timeout=30).json()
        return r.get("access_token") or tok
    except (requests.RequestException, ValueError):
        return tok


def post_facebook(p):
    with open(p["image"], "rb") as f:
        r = requests.post(f"{GRAPH}/{ENV('FB_PAGE_ID')}/photos", timeout=60, files={"source": f},
                          data={"caption": p["long"], "access_token": page_token()})
    r.raise_for_status()


def post_instagram(p):
    ig, tok = ENV("IG_USER_ID"), ENV("FB_PAGE_TOKEN")
    url = public_image_url(p)
    c = requests.post(f"{GRAPH}/{ig}/media", timeout=60,
                      data={"image_url": url, "caption": p["long"][:2150], "access_token": tok})
    c.raise_for_status()
    cid = c.json()["id"]
    for _ in range(20):
        st = requests.get(f"{GRAPH}/{cid}", params={"fields": "status_code", "access_token": tok}, timeout=30).json()
        if st.get("status_code") == "FINISHED":
            break
        if st.get("status_code") == "ERROR":
            raise RuntimeError(f"Instagram processing error: {st}")
        time.sleep(6)
    r = requests.post(f"{GRAPH}/{ig}/media_publish", data={"creation_id": cid, "access_token": tok}, timeout=60)
    r.raise_for_status()


def post_tiktok(p):
    from tiktok_auth import access_token
    tok = {"access_token": access_token()}
    h = {"Authorization": f"Bearer {tok['access_token']}", "Content-Type": "application/json; charset=UTF-8"}
    info = requests.post("https://open.tiktokapis.com/v2/post/publish/creator_info/query/", headers=h, timeout=30).json()
    opts = (info.get("data") or {}).get("privacy_level_options") or ["SELF_ONLY"]
    privacy = "PUBLIC_TO_EVERYONE" if "PUBLIC_TO_EVERYONE" in opts else opts[0]
    body = {"post_info": {"title": p["title"][:90], "description": p["long"][:2200], "privacy_level": privacy,
                          "disable_comment": False, "auto_add_music": False},
            "source_info": {"source": "PULL_FROM_URL", "photo_cover_index": 0, "photo_images": [public_image_url(p, ".jpg")]},
            "post_mode": "DIRECT_POST", "media_type": "PHOTO"}
    r = requests.post("https://open.tiktokapis.com/v2/post/publish/content/init/", headers=h, json=body, timeout=60)
    if "unaudited_client" in r.text and privacy != "SELF_ONLY":
        # Until TikTok approves the app, posts must be "only me" on a private account.
        privacy = body["post_info"]["privacy_level"] = "SELF_ONLY"
        r = requests.post("https://open.tiktokapis.com/v2/post/publish/content/init/", headers=h, json=body, timeout=60)
    r.raise_for_status()
    if (r.json().get("error") or {}).get("code") not in (None, "ok"):
        raise RuntimeError(r.text[:300])
    pub = (r.json().get("data") or {}).get("publish_id")
    for _ in range(24):  # confirm TikTok finished processing (max ~4 min)
        time.sleep(10)
        st = requests.post("https://open.tiktokapis.com/v2/post/publish/status/fetch/", headers=h,
                           json={"publish_id": pub}, timeout=30).json().get("data") or {}
        if st.get("status") == "PUBLISH_COMPLETE":
            break
        if st.get("status") == "FAILED":
            raise RuntimeError(f"TikTok processing failed: {st.get('fail_reason')}")
    if privacy != "PUBLIC_TO_EVERYONE":
        print("  NOTE: TikTok posted privately - the app must pass TikTok's audit before posts can be public.")


PLATFORMS = [
    ("x", ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET"], post_x),
    ("bluesky", ["BSKY_HANDLE", "BSKY_APP_PASSWORD"], post_bluesky),
    ("mastodon", ["MASTODON_INSTANCE", "MASTODON_TOKEN"], post_mastodon),
    ("telegram", ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"], post_telegram),
    ("facebook", ["FB_PAGE_ID", "FB_PAGE_TOKEN"], post_facebook),
    ("instagram", ["IG_USER_ID", "FB_PAGE_TOKEN"], post_instagram),
    ("tiktok", ["TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET"], post_tiktok),
]


def publish(post, log):
    done = log.setdefault(post["id"], {})
    for name, keys, fn in PLATFORMS:
        if done.get(name) == "ok":
            continue
        if not all(ENV(k) for k in keys):
            continue
        if name == "tiktok" and not (os.path.exists(os.path.join(DATA, "tiktok_token.enc")) or ENV("TIKTOK_REFRESH_TOKEN")):
            continue
        if DRY:
            print(f"[dry-run] {name}: {post['short'][:120]!r}")
            continue
        try:
            fn(post)
            done[name] = "ok"
            print(f"  {name}: posted {post['id']}")
        except Exception as e:  # keep going with the other platforms
            msg = getattr(getattr(e, "response", None), "text", "") or str(e)
            done[name] = f"error: {msg[:200]}"
            print(f"  {name}: FAILED {post['id']}: {msg[:300]}")
    return all(v == "ok" for v in done.values()) if done else True


def main():
    mode = next((a for a in sys.argv[1:] if not a.startswith("--")), "alerts")
    if not DRY and not any(all(ENV(k) for k in keys) for _, keys, _ in PLATFORMS):
        print("No social accounts connected yet - nothing posted, queue kept for later.")
        return
    log_path = os.path.join(DATA, "post_log.json")
    log = load_json(log_path, {})
    events = {e["id"]: e for e in load_json(os.path.join(DATA, "events.json"), [])}
    posts = []
    if mode == "alerts":
        pending = load_json(os.path.join(DATA, "alerts_pending.json"), [])
        for a in pending[:CFG["alerts"]["max_alert_posts_per_run"]]:
            if a["id"] in events and f"alert-{a['id']}" not in log:
                posts.append(alert_post(events[a["id"]], a["reason"]))
        if not DRY:
            save_json(os.path.join(DATA, "alerts_pending.json"), pending[CFG["alerts"]["max_alert_posts_per_run"]:])
    elif mode == "weekly":
        p = weekly_post(sorted(events.values(), key=lambda e: e["date"], reverse=True))
        if p:  # platforms that already received it are skipped inside publish()
            posts.append(p)
    elif mode == "queue":
        posts = queued_posts()
    configured = [n for n, keys, _ in PLATFORMS if all(ENV(k) for k in keys)]
    print(f"Mode {mode}: {len(posts)} post(s); platforms configured: {configured or 'none yet'}")
    for p in posts:
        if DRY:
            print("-" * 60 + f"\n{p['long']}\n")
        publish(p, log)
    if not DRY:
        save_json(log_path, dict(list(log.items())[-500:]))
        if mode == "queue" and posts:
            q = load_json(os.path.join(DATA, "posts_queue.json"), [])
            ids = {p["id"] for p in posts}
            for item in q:
                if item["id"] in ids:
                    item["status"] = "posted"
                    item["posted_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
            save_json(os.path.join(DATA, "posts_queue.json"), q[-100:])


if __name__ == "__main__":
    main()
