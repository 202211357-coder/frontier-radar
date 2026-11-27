#!/usr/bin/env python3
"""Frontier model release tracker.

Polls official Google / OpenAI / Anthropic pages, detects new model releases and
deprecations, updates site/data.json + site/feed.xml, and sends notifications.
Runs anywhere Python runs (GitHub Actions cron by default). No Claude session needed.

Usage:
  python tracker/track.py               # normal run
  python tracker/track.py --bootstrap   # first run: remember everything that exists now, add nothing
  python tracker/track.py --dry-run     # print what would change, write nothing, notify nobody
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import os
import re
import sys
import time
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path
from defusedxml import ElementTree as ET  # rejects entity-expansion (billion laughs) payloads

import requests

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
STATE = ROOT / "tracker" / "state.json"
KST = dt.timezone(dt.timedelta(hours=9))
UA = {"User-Agent": "Mozilla/5.0 (compatible; frontier-radar/1.0; +https://github.com)"}

# ---------------------------------------------------------------- sources
SOURCES = [
    # dated changelog pages: split into sections by "Month D, YYYY"
    {"id": "gem-changelog", "name": "Gemini API changelog", "vendor": "google", "kind": "dated", "url": "https://aistudio.google.com/docs/changelog"},
    {"id": "claude-rn", "name": "Claude Platform 릴리스 노트", "vendor": "anthropic", "kind": "dated", "url": "https://platform.claude.com/docs/en/release-notes/overview"},
    {"id": "openai-rn", "name": "OpenAI 모델 릴리스 노트", "vendor": "openai", "kind": "dated", "url": "https://help.openai.com/en/articles/9624314-model-release-notes"},
    # news feeds
    {"id": "openai-news", "name": "OpenAI News RSS", "vendor": "openai", "kind": "rss", "url": "https://openai.com/news/rss.xml"},
    {"id": "google-ai", "name": "Google AI 블로그 RSS", "vendor": "google", "kind": "rss", "url": "https://blog.google/technology/ai/rss/"},
    {"id": "deepmind", "name": "Google DeepMind 블로그 RSS", "vendor": "google", "kind": "rss", "url": "https://deepmind.google/blog/rss.xml"},
    # Anthropic has no news feed: watch article links on the news index
    {"id": "anthropic-news", "name": "Anthropic News", "vendor": "anthropic", "kind": "links", "url": "https://www.anthropic.com/news", "base": "https://www.anthropic.com"},
]
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
DATE_RE = re.compile(rf"\b({MONTHS}) (\d{{1,2}}), (20\d\d)\b")
NAME_RE = re.compile(
    r"(GPT[-‑ ]?\d[\w.\-]*(?: (?:Astra|Sol|Terra|Luna|Cyber|Chat|Pro|mini|nano|Codex|Live|Rosalind)\b)*"
    r"|gpt-[\w.\-]+|o\d(?:-[\w]+)?\b"
    r"|Gemini(?: \d[\d.]*)?(?: (?:Pro|Flash|Flash-Lite|Ultra|Neon|Carbon|Argon|Hydrogen|Omni|Decision|Robotics|Nano)\b)+(?: [\d.]+)?(?: Flash)?"
    r"|gemini-[\w.\-]+|Gemma \d[\w.]*|Genie \d|Veo \d[\w.]*|Imagen \d[\w.]*"
    r"|Claude (?:Opus|Sonnet|Haiku|Fable|Mythos) [\d.]+|claude-(?:opus|sonnet|haiku|fable|mythos)-[\d\-]+)", re.I)
ACTION_RE = re.compile(r"introduc|launch|releas|now available|generally available|\bGA\b|preview|experimental|rolling out|new model"
                       r"|deprecat|retir|sunset|shut ?down|discontinu|routes? to|routing|removal|removed", re.I)
RETIRE_RE = re.compile(r"deprecat|retir|sunset|shut ?down|discontinu|routes? to|routing|removal|removed", re.I)


MAX_BYTES = 8 * 1024 * 1024  # an official page or feed is far smaller; anything bigger is refused


def get(url: str, **kw) -> requests.Response:
    if not url.startswith("https://"):
        raise ValueError(f"refusing non-https url: {url[:80]}")
    r = requests.get(url, headers={**UA, **kw.pop("headers", {})}, timeout=40, stream=True, **kw)
    r.raise_for_status()
    body = b""
    for chunk in r.iter_content(65536):
        body += chunk
        if len(body) > MAX_BYTES:
            r.close()
            raise ValueError(f"response over {MAX_BYTES} bytes: {url[:80]}")
    r._content = body
    return r


def safe_url(u: str | None) -> str | None:
    """Only plain https links to the vendors' own sites reach the page."""
    if not u or not re.match(r"^https://[A-Za-z0-9.-]+(/[^\s\"'<>]*)?$", u):
        return None
    host = u.split("/")[2].lower()
    ok = ("openai.com", "anthropic.com", "claude.com", "google.com", "google", "deepmind.google", "blog.google", "googleblog.com")
    return u if any(host == h or host.endswith("." + h) for h in ok) else None


def clean(t: str, n: int) -> str:
    """Plain text only: no control characters, bounded length."""
    return re.sub(r"[\x00-\x1f\x7f]", " ", t or "").strip()[:n]


def html_text(s: str) -> str:
    s = re.sub(r"(?is)<(script|style|svg)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</(p|li|h\d|div|tr)>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t ]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n", s).strip()


def iso(m: re.Match) -> str:
    return dt.date(int(m.group(3)), MONTHS.split("|").index(m.group(1)) + 1, int(m.group(2))).isoformat()


def key_of(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


# ---------------------------------------------------------------- collectors
def collect_dated(src):
    text = html_text(get(src["url"]).text)
    # a date opens a section only when it starts a line (dates inside sentences are deadlines, not headers)
    marks = [m for m in DATE_RE.finditer(text)
             if re.fullmatch(r"#*\s*", text[text.rfind("\n", 0, m.start()) + 1: m.start()])
             and len(text[m.end(): (text.find("\n", m.end()) + 1 or len(text))].strip()) < 40]
    out = []
    for i, m in enumerate(marks):
        body = text[m.end(): marks[i + 1].start() if i + 1 < len(marks) else m.end() + 3000].strip()
        if len(body) < 30:
            continue
        # changelogs hold several bullets per date: one candidate per bullet/line
        # markdown changelogs (Gemini) use bullets that wrap over lines; HTML notes (Claude, OpenAI) use one paragraph per line
        parts = re.split(r"\n\s*(?:\*|•|-)\s+", body) if re.search(r"\n\s*\*\s+", body) else body.split("\n")
        for chunk in parts[:16]:
            chunk = re.sub(r"\s+", " ", chunk).strip()
            if len(chunk) < 25:
                continue
            title = re.split(r"(?<=[.:])\s", re.sub(r"[*`]", "", chunk), maxsplit=1)[0][:160]
            out.append({"key": key_of(src["id"], iso(m), chunk[:200]), "vendor": src["vendor"], "source": src["id"],
                        "date": iso(m), "title": title, "text": chunk[:1500], "url": src["url"]})
    return out


def collect_rss(src):
    root = ET.fromstring(get(src["url"]).content)
    out = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        desc = html_text(it.findtext("description") or "")
        try:
            date = parsedate_to_datetime(it.findtext("pubDate")).astimezone(KST).date().isoformat()
        except Exception:
            date = dt.datetime.now(KST).date().isoformat()
        out.append({"key": key_of(src["id"], link or title), "vendor": src["vendor"], "source": src["id"],
                    "date": date, "title": title, "text": f"{title}. {desc}"[:1500], "url": link})
        if len(out) >= 60:
            break
    return out


def collect_links(src):
    page = get(src["url"]).text
    out, seen = [], set()
    for href, inner in re.findall(r'href="(/news/[a-z0-9\-]+)"[^>]*>(.*?)</a>', page, re.S):
        if href in seen:
            continue
        seen.add(href)
        title = html_text(inner)[:200] or href.rsplit("/", 1)[-1].replace("-", " ")
        out.append({"key": key_of(src["id"], href), "vendor": src["vendor"], "source": src["id"],
                    "date": dt.datetime.now(KST).date().isoformat(), "title": title,
                    "text": title + " " + href.rsplit("/", 1)[-1].replace("-", " "), "url": src["base"] + href})
    return out


COLLECT = {"dated": collect_dated, "rss": collect_rss, "links": collect_links}


def relevant(c) -> bool:
    if c["source"] in ("openai-news", "google-ai", "deepmind", "anthropic-news"):
        # news feeds carry customer stories that mention models: the title itself must announce something
        return bool(NAME_RE.search(c["title"]) and ACTION_RE.search(c["title"]))
    head = c["title"] + " " + c["text"][:400]
    return bool(NAME_RE.search(head) and ACTION_RE.search(head))


def norm(model: str) -> str:
    return re.sub(r"[^a-z0-9]", "", model.lower().replace("claude", "").replace("gemini", "gem"))


# ---------------------------------------------------------------- merge into site data
def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:48]


def to_event(c):
    model = (NAME_RE.search(c["title"] + " " + c["text"]) or [c["title"]])[0]
    typ = "retire" if RETIRE_RE.search(c["title"] + " " + c["text"][:300]) else "launch"
    return {
        "id": f"{c['vendor'][0]}-{slug(model)}-{c['date'][5:].replace('-', '')}",
        "date": c["date"], "vendor": c["vendor"], "type": typ, "model": clean(model, 80),
        "title": clean(c["title"], 120),
        "summary": clean(c["text"], 240),
        "status": "auto", "src": None, "url": safe_url(c.get("url")),
    }


def merge(data, cands):
    added = []
    known = [(e["vendor"], norm(e["model"]), e["date"]) for e in data["events"]]

    def dup(ev):  # same vendor, overlapping model name, within 4 days = same release seen from another source
        a = norm(ev["model"])
        d0 = dt.date.fromisoformat(ev["date"])
        return any(v == ev["vendor"] and (a in b or b in a) and abs((dt.date.fromisoformat(d) - d0).days) <= 4
                   for v, b, d in known if b)
    ids = {e["id"] for e in data["events"]}
    for c in sorted(cands, key=lambda x: x["date"]):
        ev = to_event(c)
        if dup(ev):
            continue
        while ev["id"] in ids:
            ev["id"] += "x"
        if ev["url"]:
            data["sources"][ev["id"]] = {"title": clean(c["title"], 120), "url": ev["url"]}
            ev["src"] = ev["id"]
        ev.pop("url")
        data["events"].append(ev)
        ids.add(ev["id"])
        known.append((ev["vendor"], norm(ev["model"]), ev["date"]))
        added.append(ev)
        if ev["type"] == "retire":  # a dated deadline in a retirement notice becomes an upcoming item
            for d in sorted({iso(m) for m in DATE_RE.finditer(c["text"]) if iso(m) > c["date"]})[:2]:
                data["upcoming"].append({"date": d, "vendor": ev["vendor"], "title": f"{ev['model']} 변경 적용",
                                         "detail": ev["summary"][:80], "src": ev["src"]})
    return added


# ---------------------------------------------------------------- outputs
def write_feed(data, site_url):
    items = sorted(data["events"], key=lambda e: e["date"], reverse=True)[:40]
    parts = [f"<item><title>{html.escape(e['title'])}</title><link>{html.escape(site_url + '#' + e['vendor'])}</link>"
             f"<guid isPermaLink=\"false\">{e['id']}</guid><pubDate>{format_datetime(dt.datetime.fromisoformat(e['date'] + 'T09:00:00+09:00'))}</pubDate>"
             f"<description>{html.escape(e['summary'])}</description></item>" for e in items]
    (SITE / "feed.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel><title>프런티어 모델 레이더</title>'
        f"<link>{html.escape(site_url)}</link><description>Gemini·GPT·Claude 신규 모델과 퇴역 공지</description>{''.join(parts)}</channel></rss>",
        encoding="utf-8")


def notify(added, site_url):
    """Send alerts; return the names of channels that accepted the message."""
    sent = []
    if not added:
        return sent
    head = ", ".join(f"{e['model']}" for e in added[:3]) + (f" 외 {len(added) - 3}건" if len(added) > 3 else "")
    body = "\n".join(f"• [{e['vendor']}] {e['date']} {e['title']}" for e in added[:10])
    title = f"새 AI 모델 소식: {head}"
    if os.environ.get("NTFY_TOPIC"):
        server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
        try:
            r = requests.post(f"{server}/{os.environ['NTFY_TOPIC']}", data=body.encode(),
                              headers={"Title": title.encode(), "Click": site_url, "Tags": "rocket"}, timeout=20)
            if r.ok:
                sent.append("ntfy")
        except Exception as e:  # noqa: BLE001
            print(f"[warn] ntfy: {e}", file=sys.stderr)
    if os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"):
        try:
            r = requests.post(f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage",
                              json={"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": f"{title}\n{body}\n{site_url}"}, timeout=20)
            if r.ok:
                sent.append("telegram")
        except Exception as e:  # noqa: BLE001
            print(f"[warn] telegram: {e}", file=sys.stderr)
    if os.environ.get("WEBHOOK_URL"):
        u = os.environ["WEBHOOK_URL"]
        payload = {"content": f"**{title}**\n{body}\n{site_url}"} if "discord" in u else {"text": f"*{title}*\n{body}\n{site_url}"}
        try:
            if requests.post(u, json=payload, timeout=20).ok:
                sent.append("webhook")
        except Exception as e:  # noqa: BLE001
            print(f"[warn] webhook: {e}", file=sys.stderr)
    return sent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bootstrap", action="store_true", help="remember current items without adding events")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    site_url = os.environ.get("SITE_URL", "")

    data = json.loads((SITE / "data.json").read_text(encoding="utf-8"))
    state = json.loads(STATE.read_text()) if STATE.exists() else {"seen": []}
    seen = set(state["seen"])
    bootstrap = args.bootstrap or not STATE.exists()

    cands, errors, watch = [], [], []
    for src in SOURCES:
        row = {k: src[k] for k in ("id", "vendor", "name", "kind", "url")}
        for attempt in (1, 2, 3):  # official sites sometimes time out once; retry before calling it an error
            try:
                got = COLLECT[src["kind"]](src)
                cands += got
                row.update(ok=True, items=len(got))
                row.pop("error", None)
                break
            except Exception as e:  # noqa: BLE001
                row.update(ok=False, items=0, error=clean(str(e), 160))
                if attempt == 3:
                    errors.append(f"{src['id']}: {row['error']}")
                else:
                    time.sleep(5 * attempt)
        watch.append(row)
    fresh = [c for c in cands if c["key"] not in seen]
    rel = [c for c in fresh if relevant(c)]
    print(f"collected {len(cands)} items, {len(fresh)} unseen, {len(rel)} model-related; errors: {errors or 'none'}")

    added = []
    if not bootstrap:
        cutoff = (dt.datetime.now(KST).date() - dt.timedelta(days=21)).isoformat()
        rel = [c for c in rel if c["date"] >= cutoff]  # an old page section that just appeared is not news
        added = merge(data, rel)
    for e in added:
        print(f"  + {e['date']} [{e['vendor']}] {e['type']}: {e['title']}")

    today = dt.datetime.now(KST).date().isoformat()
    data["upcoming"] = sorted([u for u in data["upcoming"] if u["date"] >= today], key=lambda u: u["date"])
    data["updated"] = today
    data["checked"] = dt.datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    data["errors"] = errors
    data["watch"] = watch

    if args.dry_run:
        print("dry run: nothing written")
        return
    sent = notify(added, site_url)
    if added:
        data.setdefault("alerts", []).insert(0, {"at": data["checked"], "count": len(added), "channels": sent,
                                                 "items": [e["id"] for e in added][:20]})
        data["alerts"] = data["alerts"][:100]
    (SITE / "data.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    write_feed(data, site_url)
    STATE.write_text(json.dumps({"seen": sorted(seen | {c["key"] for c in cands})}, indent=0))
    if bootstrap:
        print(f"bootstrap: remembered {len(cands)} items; next runs report only new ones")


if __name__ == "__main__":
    main()
