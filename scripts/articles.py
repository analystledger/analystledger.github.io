"""Articles: load approved articles for the site, and turn approved GitHub issues into article files.

Workflow
  * Anyone (staff or correspondent) submits an article as a GitHub issue using the
    "Submit an article" form. It gets the labels `article` + `pending-review`.
  * An editor (config.json -> "editors") adds the label `approved`.
  * .github/workflows/articles.yml runs `python scripts/articles.py publish "$GITHUB_EVENT_PATH"`,
    which writes articles/<slug>.md, then rebuilds the site.
  * Correspondent applications work the same way: `approved` on a `correspondent-application`
    issue runs `python scripts/articles.py correspondent "$GITHUB_EVENT_PATH"`.
Nothing is published unless an editor applied the label.
"""
import html
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DATA, ROOT, config, load_json, save_json, slugify  # noqa: E402

ART_DIR = os.path.join(ROOT, "articles")
CORR_FILE = os.path.join(DATA, "correspondents.json")
EMPTY = {"", "_no response_", "none", "n/a"}


# ---------- reading article files ----------
def parse_front(text):
    """Front matter: 'key: value' lines between --- markers; 'sources' continues on following lines."""
    meta, body = {}, text
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if not m:
        return meta, body
    head, body = m.group(1), m.group(2)
    key = None
    for line in head.splitlines():
        km = re.match(r"^([a-z_]+):\s*(.*)$", line)
        if km and km.group(1) in {"title", "investor", "firm", "summary", "tickers", "sources", "author",
                                  "author_login", "author_type", "date", "issue", "status", "slug"}:
            key = km.group(1)
            meta[key] = km.group(2).strip()
        elif key == "sources" and line.strip():
            meta["sources"] += "\n" + line.strip()
    srcs = []
    for ln in (meta.get("sources") or "").splitlines():
        if "|" in ln:
            name, url = ln.rsplit("|", 1)
            if url.strip().startswith(("http://", "https://")):
                srcs.append({"name": name.strip(), "url": url.strip()})
    meta["sources"] = srcs
    meta["tickers"] = [t.strip().upper() for t in (meta.get("tickers") or "").split(",") if t.strip()][:10]
    return meta, body


def render_md(body):
    """Markdown -> HTML with raw HTML disabled and only http(s)/mailto links kept."""
    import markdown
    safe = body.replace("<", "&lt;")
    out = markdown.markdown(safe, extensions=["extra", "sane_lists"], output_format="html")
    out = re.sub(r'(href|src)="(?!https?://|mailto:|#)[^"]*"', r'\1="#"', out)
    out = out.replace("<a href=\"http", "<a rel=\"noopener nofollow\" target=\"_blank\" href=\"http")
    return out


def load_articles():
    arts = []
    if not os.path.isdir(ART_DIR):
        return arts
    for fn in sorted(os.listdir(ART_DIR)):
        if not fn.endswith(".md"):
            continue
        with open(os.path.join(ART_DIR, fn), encoding="utf-8") as f:
            meta, body = parse_front(f.read())
        if meta.get("status", "approved") != "approved" or not meta.get("title"):
            continue
        meta["slug"] = fn[:-3]
        meta["html"] = render_md(body)
        meta["words"] = len(body.split())
        meta.setdefault("date", "")
        meta.setdefault("author", config().get("staff_byline", "Staff"))
        meta.setdefault("author_type", "staff")
        arts.append(meta)
    arts.sort(key=lambda a: a["date"], reverse=True)
    return arts


# ---------- issue forms ----------
def parse_issue_form(body):
    """GitHub issue forms render as '### Label\\n\\nvalue' blocks."""
    fields, cur = {}, None
    for line in (body or "").replace("\r\n", "\n").split("\n"):
        m = re.match(r"^###\s+(.+?)\s*$", line)
        if m:
            cur = m.group(1).lower()
            fields[cur] = []
        elif cur is not None:
            fields[cur].append(line)
    out = {}
    for k, v in fields.items():
        val = "\n".join(v).strip()
        out[k] = "" if val.lower() in EMPTY else val
    return out


def field(f, *names):
    for n in names:
        for k, v in f.items():
            if k.startswith(n):
                return v
    return ""


def one_line(s, n):
    return re.sub(r"\s+", " ", s or "").strip()[:n]


def _event(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _check_editor(ev):
    sender = (ev.get("sender") or {}).get("login", "")
    editors = {e.lower() for e in config().get("editors", [])}
    if sender.lower() not in editors:
        sys.exit(f"Label added by {sender!r}, who is not in config.json editors; nothing published.")
    return sender


def publish(event_path):
    ev = _event(event_path)
    _check_editor(ev)
    issue = ev["issue"]
    f = parse_issue_form(issue.get("body", ""))
    title = one_line(field(f, "headline") or issue["title"].removeprefix("[Article]").strip(), 120)
    body = field(f, "article")
    if not title or len(body.split()) < 80:
        sys.exit("Headline missing or article shorter than 80 words; nothing published.")
    login = issue["user"]["login"]
    corr = {c["login"].lower(): c for c in load_json(CORR_FILE, [])}
    editors = {e.lower() for e in config().get("editors", [])}
    if login.lower() in corr:
        author, atype = corr[login.lower()]["name"], "correspondent"
    elif login.lower() in editors or login.endswith("[bot]"):
        author, atype = field(f, "byline") or config().get("staff_byline", "Staff"), "staff"
    else:
        author, atype = login, "correspondent"
    sources = []
    for ln in field(f, "sources").splitlines():
        ln = ln.strip().lstrip("-* ").strip()
        m = re.search(r"https?://\S+", ln)
        if m:
            name = one_line(ln.replace(m.group(0), "").strip(" |–-:"), 120) or re.sub(r"^https?://(www\.)?", "", m.group(0)).split("/")[0]
            sources.append(f"{name} | {m.group(0).rstrip(').,')}")
    disc = one_line(field(f, "disclosure"), 400)
    if disc:
        body = body.rstrip() + f"\n\n*Author disclosure: {disc}*"
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    slug = slugify(title)[:70].strip("-")
    os.makedirs(ART_DIR, exist_ok=True)
    existing = [fn for fn in os.listdir(ART_DIR) if fn.endswith(".md")]
    for fn in existing:  # re-approving the same issue updates its article
        with open(os.path.join(ART_DIR, fn), encoding="utf-8") as fh:
            if re.search(rf"^issue: {issue['number']}\s*$", fh.read(), re.M):
                slug = fn[:-3]
                break
    else:
        if f"{slug}.md" in existing:
            slug = f"{slug}-{issue['number']}"
    lines = ["---", f"title: {title}", f"summary: {one_line(field(f, 'summary'), 400)}",
             f"investor: {one_line(field(f, 'investor'), 80)}", f"tickers: {one_line(field(f, 'tickers'), 80)}",
             f"author: {one_line(author, 80)}", f"author_login: {login}", f"author_type: {atype}",
             f"date: {date}", f"issue: {issue['number']}", "status: approved",
             "sources: " + ("\n".join(sources) if sources else ""), "---", body.strip(), ""]
    with open(os.path.join(ART_DIR, f"{slug}.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print(slug)


def add_correspondent(event_path):
    ev = _event(event_path)
    _check_editor(ev)
    issue = ev["issue"]
    f = parse_issue_form(issue.get("body", ""))
    login = issue["user"]["login"]
    corr = [c for c in load_json(CORR_FILE, []) if c["login"].lower() != login.lower()]
    corr.append({"login": login, "name": one_line(field(f, "display name") or login, 60),
                 "bio": one_line(field(f, "short bio"), 280),
                 "since": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "issue": issue["number"]})
    save_json(CORR_FILE, corr)
    print(login)


def from_markdown_file(path):
    """Helper for staff drafts: print an issue body (form format) for a drafted .md file."""
    with open(path, encoding="utf-8") as fh:
        meta, body = parse_front(fh.read())
    srcs = "\n".join(f"- {s['name']} | {s['url']}" for s in meta["sources"])
    print(f"### Headline\n\n{meta.get('title','')}\n\n### Summary\n\n{meta.get('summary','')}\n\n"
          f"### Investor (optional)\n\n{meta.get('investor','') or '_No response_'}\n\n"
          f"### Tickers (optional)\n\n{', '.join(meta['tickers']) or '_No response_'}\n\n"
          f"### Article\n\n{body.strip()}\n\n### Sources\n\n{srcs}\n\n"
          f"### Byline (editors only, optional)\n\n_No response_\n\n### Declarations\n\n"
          "- [X] The text is my own work, written in my own words.\n"
          "- [X] It contains no buy/sell recommendations or price targets of my own.\n"
          "- [X] I have disclosed below any position I hold in the stocks discussed.\n\n"
          "### Disclosure of positions\n\n_No response_")


if __name__ == "__main__":
    cmd, arg = sys.argv[1], sys.argv[2]
    {"publish": publish, "correspondent": add_correspondent, "issue-body": from_markdown_file}[cmd](arg)
