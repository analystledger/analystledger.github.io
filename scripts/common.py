"""Shared helpers: config, event schema, normalisation, file IO."""
import hashlib
import json
import os
import re
from datetime import date, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
DOCS = os.path.join(ROOT, "docs")

ACTIONS = {
    "upgrade": "Upgrade",
    "downgrade": "Downgrade",
    "initiate": "Initiates coverage",
    "reiterate": "Reiterates",
    "target_raise": "Raises target",
    "target_cut": "Cuts target",
    "terminate": "Drops coverage",
}

BULLISH = {"buy", "strong buy", "outperform", "overweight", "accumulate", "positive", "add",
           "market outperform", "sector outperform", "top pick", "conviction buy", "long-term buy",
           "moderate buy", "speculative buy"}
BEARISH = {"sell", "strong sell", "underperform", "underweight", "reduce", "negative",
           "market underperform", "sector underperform", "moderate sell"}


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False, sort_keys=False)
    os.replace(tmp, path)


def config():
    return load_json(os.path.join(ROOT, "config.json"), {})


def slugify(text):
    text = (text or "").lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "unknown"


def stance(rating):
    r = (rating or "").strip().lower()
    if not r:
        return None
    if r in BULLISH:
        return "bullish"
    if r in BEARISH:
        return "bearish"
    return "neutral"


def to_float(v):
    try:
        if v in (None, "", "N/A"):
            return None
        return round(float(str(v).replace("$", "").replace(",", "")), 2)
    except ValueError:
        return None


def parse_date(v):
    if not v:
        return None
    s = str(v)[:10]
    try:
        return datetime.strptime(s, "%Y-%m-%d").date().isoformat()
    except ValueError:
        return None


def infer_action(ev):
    """Fill in action when a source only gives from/to values."""
    a = (ev.get("action") or "").lower().strip()
    aliases = {"up": "upgrade", "upgrades": "upgrade", "down": "downgrade", "downgrades": "downgrade",
               "init": "initiate", "initiates": "initiate", "initiated": "initiate",
               "initiates coverage on": "initiate", "maintains": "reiterate", "maintain": "reiterate",
               "reiterates": "reiterate", "reiterated": "reiterate", "hold": "reiterate",
               "terminates coverage on": "terminate", "raises": "target_raise", "lowers": "target_cut"}
    a = aliases.get(a, a)
    if a in ACTIONS and a != "reiterate":
        return a
    order = {"bearish": 0, "neutral": 1, "bullish": 2}
    s_from, s_to = stance(ev.get("rating_from")), stance(ev.get("rating_to"))
    if s_from and s_to and order[s_to] > order[s_from]:
        return "upgrade"
    if s_from and s_to and order[s_to] < order[s_from]:
        return "downgrade"
    pf, pt = ev.get("pt_from"), ev.get("pt_to")
    if pf and pt and pt > pf:
        return "target_raise"
    if pf and pt and pt < pf:
        return "target_cut"
    return a if a in ACTIONS else "reiterate"


def normalise(raw, source):
    """Return a clean event dict or None if unusable."""
    ev = {
        "date": parse_date(raw.get("date")),
        "ticker": (raw.get("ticker") or "").upper().strip(),
        "company": (raw.get("company") or "").strip(),
        "analyst": (raw.get("analyst") or "").strip(),
        "firm": (raw.get("firm") or "").strip(),
        "rating_from": (raw.get("rating_from") or "").strip(),
        "rating_to": (raw.get("rating_to") or "").strip(),
        "pt_from": to_float(raw.get("pt_from")),
        "pt_to": to_float(raw.get("pt_to")),
        "price_at_rating": to_float(raw.get("price_at_rating")),
        "source": source,
        "source_url": (raw.get("source_url") or "").strip(),
        "action": raw.get("action"),
    }
    if not ev["date"] or not ev["ticker"] or not ev["firm"]:
        return None
    if ev["date"] > date.today().isoformat():
        return None
    ev["action"] = infer_action(ev)
    key = "|".join([ev["date"], ev["ticker"], slugify(ev["firm"]), slugify(ev["analyst"]),
                    ev["action"], str(ev["pt_to"] or ""), slugify(ev["rating_to"])])
    ev["id"] = hashlib.sha1(key.encode()).hexdigest()[:12]
    return ev
