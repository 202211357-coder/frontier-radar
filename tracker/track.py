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
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path
from xml.etree import ElementTree as ET

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
# Optional: model-list APIs (only run when the key is set). New model IDs are the most reliable signal.
MODEL_APIS = [
    {"id": "api-openai", "vendor": "openai", "env": "OPENAI_API_KEY", "url": "https://api.openai.com/v1/models",
     "headers": lambda k: {"Authorization": f"Bearer {k}"}, "ids": lambda j: [m["id"] for m in j.get("data", [])]},
    {"id": "api-anthropic", "vendor": "anthropic", "env": "ANTHROPIC_API_KEY", "url": "https://api.anthropic.com/v1/models?limit=1000",
     "headers": lambda k: {"x-api-key": k, "anthropic-version": "2023-06-01"}, "ids": lambda j: [m["id"] for m in j.get("data", [])]},
    {"id": "api-gemini", "vendor": "google", "env": "GEMINI_API_KEY", "url": "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000",
     "headers": lambda k: {"x-goog-api-key": k}, "ids": lambda j: [m["name"].split("/")[-1] for m in j.get("models", [])]},
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
SKIP_ID_RE = re.compile(r"(embedding|tts|whisper|moderation|dall-e|babbage|davinci|search|realtime-preview-\d{4})", re.I)


def get(url: str, **kw) -> requests.Response:
    r = requests.get(url, headers={**UA, **kw.pop("headers", {})}, timeout=40, **kw)
    r.raise_for_status()
    return r


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


def collect_model_apis():
    out = []
    for api in MODEL_APIS:
        k = os.environ.get(api["env"])
        if not k:
            continue
        try:
            ids = api["ids"](get(api["url"], headers=api["headers"](k)).json())
        except Exception as e:  # noqa: BLE001
            print(f"[warn] {api['id']}: {e}", file=sys.stderr)
            continue
        for mid in ids:
            if SKIP_ID_RE.search(mid):
                continue
            out.append({"key": key_of(api["id"], mid), "vendor": api["vendor"], "source": api["id"],
                        "date": dt.datetime.now(KST).date().isoformat(), "title": f"API에 새 모델 ID: {mid}",
                        "text": f"New model id {mid} is now listed in the {api['vendor']} models API (now available).",
                        "url": "", "model": mid, "force": True})
    return out


COLLECT = {"dated": collect_dated, "rss": collect_rss, "links": collect_links}


def relevant(c) -> bool:
    if c.get("force"):
        return True
    if c["source"] in ("openai-news", "google-ai", "deepmind", "anthropic-news"):
        # news feeds carry customer stories that mention models: the title itself must announce something
        return bool(NAME_RE.search(c["title"]) and ACTION_RE.search(c["title"]))
    head = c["title"] + " " + c["text"][:400]
    return bool(NAME_RE.search(head) and ACTION_RE.search(head))


def norm(model: str) -> str:
    return re.sub(r"[^a-z0-9]", "", model.lower().replace("claude", "").replace("gemini", "gem"))


# ---------------------------------------------------------------- optional enrichment with Claude
def enrich(c):
    """Use Claude to turn an announcement into structured data. Skipped when ANTHROPIC_API_KEY is unset."""
    if not os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("RADAR_NO_LLM"):
        return None
    try:
        import anthropic
        from pydantic import BaseModel
        from typing import Literal

        class Score(BaseModel):
            model: str
            value: float

        class Bench(BaseModel):
            name: str
            setting: str
            unit: Literal["%", "점", "Elo"]
            scores: list[Score]

        class Release(BaseModel):
            is_model_news: bool
            model: str
            type: Literal["launch", "retire", "update"]
            flagship: bool
            summary_ko: str
            price: str
            context: str
            availability: str
            previous_model: str
            improvements_ko: list[str]
            future_dates: list[str]
            benchmarks: list[Bench]

        page = c["text"]
        if c.get("url") and c["source"] not in ("gem-changelog", "claude-rn", "openai-rn"):
            try:
                page = html_text(get(c["url"]).text)[:80000]
            except Exception:  # noqa: BLE001
                pass
        client = anthropic.Anthropic()
        resp = client.beta.messages.parse(
            model="claude-opus-5-5",
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "low"},
            system=(
                "You extract facts about AI model releases from an official announcement for a Korean tracking site. "
                "Use only what the text states. Leave a string empty and a list empty when the text does not say it; "
                "never estimate or recall numbers from memory. is_model_news is true only for a new model or version, "
                "a preview, or a deprecation/retirement/routing notice; false for product features, pricing plans, "
                "research or customer stories. summary_ko is one Korean sentence. improvements_ko are short Korean "
                "phrases versus the previous model, with numbers as stated. future_dates are YYYY-MM-DD dates of "
                "scheduled retirements, routings or price changes. benchmarks copy the published table: benchmark "
                "name, effort/thinking setting as stated (empty if none), unit, and one score per model column."
            ),
            messages=[{"role": "user", "content": f"Source: {c['url']}\nTitle: {c['title']}\n\n{page}"}],
            output_format=Release,
        )
        if resp.stop_reason == "refusal" or resp.parsed_output is None:
            return None
        return resp.parsed_output.model_dump()
    except Exception as e:  # noqa: BLE001
        print(f"[warn] enrichment failed for {c['title'][:60]}: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------- merge into site data
def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:48]


def vendor_of(name: str, default: str) -> str:
    n = name.lower()
    return "openai" if re.search(r"gpt|\bo\d", n) else "google" if re.search(r"gemini|gemma|genie|veo|imagen", n) \
        else "anthropic" if re.search(r"claude|opus|sonnet|haiku|fable|mythos", n) else default


def to_event(c, info):
    model = (info or {}).get("model") or c.get("model") or (NAME_RE.search(c["title"] + " " + c["text"]) or [c["title"]])[0]
    typ = (info or {}).get("type") or ("retire" if RETIRE_RE.search(c["title"] + " " + c["text"][:300]) else "launch")
    ev = {
        "id": f"{c['vendor'][0]}-{slug(model)}-{c['date'][5:].replace('-', '')}",
        "date": c["date"], "vendor": c["vendor"], "type": typ, "model": model,
        "title": c["title"][:120] if not info else f"{model} {'출시' if typ == 'launch' else '지원 중단·퇴역' if typ == 'retire' else '변경'}",
        "summary": (info or {}).get("summary_ko") or c["text"][:180],
        "status": "auto", "src": None, "url": c.get("url") or None,
    }
    for k_src, k_dst in (("price", "price"), ("context", "context"), ("availability", "availability")):
        if info and info.get(k_src):
            ev[k_dst] = info[k_src]
    if info and info.get("flagship"):
        ev["flagship"] = True
    return ev


def merge(data, cands, enrich_on=True):
    added = []
    known = [(e["vendor"], norm(e["model"]), e["date"]) for e in data["events"]]

    def dup(ev):  # same vendor, overlapping model name, within 4 days = same release seen from another source
        a = norm(ev["model"])
        d0 = dt.date.fromisoformat(ev["date"])
        return any(v == ev["vendor"] and (a in b or b in a) and abs((dt.date.fromisoformat(d) - d0).days) <= 4
                   for v, b, d in known if b)
    ids = {e["id"] for e in data["events"]}
    for c in sorted(cands, key=lambda x: x["date"]):
        info = enrich(c) if enrich_on else None
        if info is not None and not info["is_model_news"]:
            continue
        ev = to_event(c, info)
        if dup(ev):
            continue
        while ev["id"] in ids:
            ev["id"] += "x"
        if ev["url"]:
            data["sources"][ev["id"]] = {"title": c["title"][:120], "url": ev["url"]}
            ev["src"] = ev["id"]
        ev.pop("url")
        data["events"].append(ev)
        ids.add(ev["id"])
        known.append((ev["vendor"], norm(ev["model"]), ev["date"]))
        added.append(ev)

        dates = (info or {}).get("future_dates") or [iso(m) for m in DATE_RE.finditer(c["text"]) if iso(m) > c["date"]]
        if ev["type"] == "retire":
            for d in sorted(set(dates))[:2]:
                data["upcoming"].append({"date": d, "vendor": ev["vendor"], "title": f"{ev['model']} 변경 적용", "detail": ev["summary"][:80], "src": ev["src"]})
        if info and info.get("benchmarks"):
            add_bench(data, ev, info)
    return added


def add_bench(data, ev, info):
    benches = [b for b in info["benchmarks"] if b["scores"]]
    if len(benches) < 2:
        return
    models = []
    for b in benches:
        for s in b["scores"]:
            if s["model"] not in models:
                models.append(s["model"])
    models = models[:6]
    rows = [[b["name"] + (f" ({b['setting']})" if b["setting"] else ""), b["unit"],
             [next((s["value"] for s in b["scores"] if s["model"] == m), None) for m in models]] for b in benches[:14]]
    data["benchTables"].insert(0, {"id": "t-" + ev["id"], "label": f"{data['vendors'][ev['vendor']]['short']} 발표 · {ev['model']}",
                                   "src": ev["src"], "vendor": ev["vendor"],
                                   "note": "자동 추출(검증 전). 원문 표와 대조해 확인하세요.",
                                   "models": [[m, vendor_of(m, ev["vendor"])] for m in models], "rows": rows})
    prev = info.get("previous_model")
    pairs = []
    if prev:
        for b in benches:
            now = next((s["value"] for s in b["scores"] if s["model"].lower() == ev["model"].lower()), None)
            old = next((s["value"] for s in b["scores"] if s["model"].lower() == prev.lower()), None)
            if now is not None and old is not None and b["unit"] == "%":
                pairs.append([b["name"], b["setting"] or "-", old, now])
    if ev.get("flagship"):
        f = {"vendor": ev["vendor"], "model": ev["model"], "date": ev["date"], "prev": prev or "-", "ctx": ev.get("context", "-"),
             "src": ev["src"], "notes": info.get("improvements_ko", [])[:4]}
        m = re.findall(r"\$([\d.]+)", ev.get("price", ""))
        if len(m) >= 2:
            f["in"], f["out"] = float(m[0]), float(m[1])
        if pairs:
            f["pairs"] = pairs[:8]
        data["flagships"].insert(0, f)


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
    ap.add_argument("--no-llm", action="store_true", help="skip Claude enrichment")
    args = ap.parse_args()
    site_url = os.environ.get("SITE_URL", "")

    data = json.loads((SITE / "data.json").read_text(encoding="utf-8"))
    state = json.loads(STATE.read_text()) if STATE.exists() else {"seen": []}
    seen = set(state["seen"])
    bootstrap = args.bootstrap or not STATE.exists()

    cands, errors, watch = [], [], []
    for src in SOURCES:
        row = {k: src[k] for k in ("id", "vendor", "name", "kind", "url")}
        try:
            got = COLLECT[src["kind"]](src)
            cands += got
            row.update(ok=True, items=len(got))
        except Exception as e:  # noqa: BLE001
            errors.append(f"{src['id']}: {e}")
            row.update(ok=False, items=0, error=str(e)[:160])
        watch.append(row)
    api = collect_model_apis()
    cands += api
    for a in MODEL_APIS:
        on = bool(os.environ.get(a["env"]))
        watch.append({"id": a["id"], "vendor": a["vendor"], "name": f"{a['vendor']} 모델 목록 API", "kind": "api",
                      "url": a["url"].split("?")[0], "ok": on, "items": sum(c["source"] == a["id"] for c in api),
                      **({} if on else {"off": True})})
    fresh = [c for c in cands if c["key"] not in seen]
    rel = [c for c in fresh if relevant(c)]
    print(f"collected {len(cands)} items, {len(fresh)} unseen, {len(rel)} model-related; errors: {errors or 'none'}")

    added = []
    if not bootstrap:
        cutoff = (dt.datetime.now(KST).date() - dt.timedelta(days=21)).isoformat()
        rel = [c for c in rel if c["date"] >= cutoff]  # an old page section that just appeared is not news
        added = merge(data, rel, enrich_on=not args.no_llm)
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
