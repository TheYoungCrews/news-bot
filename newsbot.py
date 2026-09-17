#!/usr/bin/env python3
"""Lotus #news bot: RSS -> LLM filter -> Slack (headline + link).

Standard library only, so the GitHub Actions job needs no installs.

Environment:
  SLACK_WEBHOOK_URL   Slack incoming webhook (required unless --dry-run)
  LLM_API_KEY         API key for an OpenAI-compatible chat endpoint (Gemini by default)
  LLM_BASE_URL        default https://generativelanguage.googleapis.com/v1beta/openai/
                      Claude: https://api.anthropic.com/v1   xAI: https://api.x.ai/v1
  LLM_MODEL           comma-separated, tried in order. default gemini-flash-latest,gemini-2.5-flash
  LLM_API_STYLE       openai or anthropic. Detected from LLM_BASE_URL, override only if needed
  LLM_MAX_TOKENS      reply budget, default 8000 (thinking models need room before the JSON)
  CONTACT_EMAIL       optional, added to the User-Agent (SEC asks bots to identify themselves)
  MAX_POSTS_PER_RUN   default 8
  MAX_AGE_HOURS       ignore items older than this, default 36
  UNFURL              "true" to let Slack show link previews, default false
"""
import argparse, hashlib, html, json, os, re, sys, time, urllib.error, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit, urlunsplit

ROOT = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(ROOT, "state", "seen.json")
SEEN_TTL = 14 * 86400
POSTED_TTL = 4 * 86400
LLM_ALERT_AFTER = 3        # consecutive failed runs before a Slack warning
FEED_ALERT_AFTER = 24      # consecutive failed runs (12h at 30 min) before a Slack warning
BATCH = 40

def log(*a): print(*a, file=sys.stderr, flush=True)
def env(k, d=None): return os.environ.get(k) or d
def now(): return time.time()

# ---------- fetching and parsing ----------

def user_agent():
    ua = "LotusNewsBot/1.0"
    if env("CONTACT_EMAIL"): ua += f" ({env('CONTACT_EMAIL')})"
    return ua

def http(url, data=None, headers=None, timeout=30):
    h = {"User-Agent": user_agent(), "Accept": "*/*"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def local(tag): return tag.rsplit("}", 1)[-1] if "}" in tag else tag

def child_text(el, *names):
    for c in el:
        if local(c.tag) in names and (c.text or "").strip():
            return c.text.strip()
    return ""

def strip_html(s, limit=400):
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = html.unescape(re.sub(r"\s+", " ", s)).strip()
    return s[:limit]

def parse_date(s):
    if not s: return None
    try:
        d = parsedate_to_datetime(s)
    except Exception:
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None
    if d.tzinfo is None: d = d.replace(tzinfo=timezone.utc)
    return d.timestamp()

def canonical(url):
    p = urlsplit(url.strip())
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), "", ""))

def parse_feed(raw, feed):
    root = ET.fromstring(raw)
    nodes = [e for e in root.iter() if local(e.tag) in ("item", "entry")]
    items = []
    for n in nodes:
        title = strip_html(child_text(n, "title"), 300)
        link = ""
        for c in n:
            if local(c.tag) == "link":
                link = (c.text or "").strip() or c.attrib.get("href", "")
                if c.attrib.get("rel", "alternate") == "alternate" and link: break
        link = link or child_text(n, "guid", "id")
        if not title or not link.startswith("http"): continue
        ts = parse_date(child_text(n, "pubDate", "published", "updated", "date"))
        cats = [(c.text or c.attrib.get("term", "")).strip() for c in n if local(c.tag) == "category"]
        summary = strip_html(child_text(n, "description", "summary", "content", "encoded"))
        items.append({
            "id": hashlib.sha1(canonical(link).encode()).hexdigest()[:16],
            "source": feed["name"], "kind": feed.get("kind", "news"),
            "title": title, "url": link, "ts": ts,
            "categories": [c for c in cats if c][:6], "summary": summary,
        })
    return items

# ---------- state ----------

def load_state():
    try:
        with open(STATE_PATH) as f: return json.load(f)
    except FileNotFoundError:
        return None

def save_state(st):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    t = now()
    st["seen"] = {k: v for k, v in st["seen"].items() if t - v < SEEN_TTL}
    st["posted"] = [p for p in st["posted"] if t - p["at"] < POSTED_TTL]
    with open(STATE_PATH, "w") as f: json.dump(st, f, indent=1, sort_keys=True)

# ---------- LLM filter ----------

PROMPT = """You filter crypto news for a company Slack channel. Follow the editorial scope below exactly.

<scope>
{scope}
</scope>

Headlines already posted to the channel in the last few days (do not post the same story again, even from a different outlet or with new wording):
<already_posted>
{posted}
</already_posted>

Candidate items, one JSON object per line:
<candidates>
{candidates}
</candidates>

Rules:
- Decide for every candidate.
- If several candidates cover the same story, post only one of them: prefer the most complete news outlet story, or the primary source (regulator or protocol forum) if no outlet covered it yet.
- priority: 1 = major (a team member would be annoyed to miss it), 2 = relevant, 3 = marginal.
- Reply with JSON only, no prose, in this shape:
{{"decisions": [{{"id": "c1", "post": true, "priority": 1, "duplicate": false, "reason": "under 12 words"}}]}}
"""

def llm_decide(cands, scope, posted_titles):
    base = env("LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/").rstrip("/")
    key = env("LLM_API_KEY")
    if not key: raise RuntimeError("LLM_API_KEY is not set")
    models = [m.strip() for m in env("LLM_MODEL", "gemini-flash-latest,gemini-2.5-flash").split(",") if m.strip()]
    style = env("LLM_API_STYLE", "anthropic" if "api.anthropic.com" in base else "openai")
    max_tokens = int(env("LLM_MAX_TOKENS", "2500"))   # also counts against Groq's tokens-per-minute limit
    batch = int(env("LLM_BATCH", "12"))

    def ask(chunk):
        lines = "\n".join(json.dumps({"id": c["cid"], "source": c["source"],
                                      "title": c["title"], "categories": c["categories"],
                                      "summary": c["summary"][:300]}, ensure_ascii=False) for c in chunk)
        prompt = PROMPT.format(scope=scope, posted="\n".join(posted_titles) or "(none)", candidates=lines)
        text, last_err = None, None
        for model in models:
            if style == "anthropic":   # native Claude Messages API
                url = base + "/messages"
                headers = {"Content-Type": "application/json", "x-api-key": key,
                           "anthropic-version": "2023-06-01"}
                payload = {"model": model, "max_tokens": max_tokens, "temperature": 0,
                           "messages": [{"role": "user", "content": prompt}]}
                pick = lambda r: r["content"][0]["text"]
            else:                      # OpenAI-compatible (Groq, Gemini, xAI, OpenRouter)
                url = base + "/chat/completions"
                headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
                payload = {"model": model, "max_tokens": max_tokens, "temperature": 0,
                           "messages": [{"role": "user", "content": prompt}]}
                if "gpt-oss" in model or "reasoning" in model:
                    payload["reasoning_effort"] = "low"   # these models think in tokens we pay for
                def pick(r):
                    m = r["choices"][0].get("message", {})
                    return m.get("content") or m.get("reasoning") or ""
            body = json.dumps(payload).encode()
            for attempt in range(3):
                try:
                    raw = http(url, data=body, timeout=120, headers=headers)
                    resp = json.loads(raw)
                    text = (pick(resp) or "").strip()
                    if not text:   # 200 with no usable content: show what came back
                        last_err = f"{model}: empty reply {json.dumps(resp)[:300]}"
                        text = None
                    break
                except urllib.error.HTTPError as e:
                    last_err = f"{model}: HTTP {e.code} {e.read()[:200]!r}"
                    if e.code in (429, 500, 502, 503, 504): time.sleep(5 * (attempt + 1)); continue
                    break
                except Exception as e:
                    last_err = f"{model}: {e}"; time.sleep(3)
            if text: break
            log("model failed:", last_err)
        if not text:
            raise RuntimeError(f"{last_err or 'LLM returned nothing'}{available_models(base, key, style)}")
        parsed = extract_json(text)
        if parsed is None:
            raise RuntimeError(f"no JSON in the reply (model may have run out of tokens thinking): ...{text[-300:]}")
        return {str(d.get("id")): d for d in parsed.get("decisions", []) if d.get("id")}

    decisions = {}
    for i in range(0, len(cands), batch):
        if i: time.sleep(float(env("LLM_PACE_SECONDS", "5")))   # stay under the free tier's per-minute budget
        chunk = cands[i:i + batch]
        got = ask(chunk)
        missing = [c for c in chunk if c["cid"] not in got]
        if missing:                      # models sometimes answer for only part of a batch
            log(f"retrying {len(missing)} candidates the model skipped")
            got.update(ask(missing))
            still = [c["cid"] for c in chunk if c["cid"] not in got]
            if still: log(f"no decision after retry, leaving unposted: {', '.join(still)}")
        decisions.update(got)
    return decisions

def extract_json(text):
    """Pull the decisions object out of a reply that may be wrapped in prose or fences."""
    for start in [m.start() for m in re.finditer(r"\{", text or "")]:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            c = text[i]
            if in_str:
                if esc: esc = False
                elif c == "\\": esc = True
                elif c == '"': in_str = False
                continue
            if c == '"': in_str = True
            elif c == "{": depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start:i + 1])
                    except Exception:
                        break
                    if isinstance(obj, dict) and "decisions" in obj: return obj
                    break
    return None

def available_models(base, key, style):
    """On failure, ask the provider which models this key can use, to put in the log."""
    if style == "anthropic": return ""
    try:
        raw = http(base + "/models", timeout=30, headers={"Authorization": f"Bearer {key}"})
        ids = [m.get("id") for m in json.loads(raw).get("data", []) if m.get("id")]
        return "  | models this key can use: " + ", ".join(sorted(ids)[:60])
    except Exception as e:
        return f"  | could not list models: {e}"

def stub_decide(cands, scope, posted_titles):
    """Keyword stand-in for plumbing tests only. Not the real filter."""
    good = re.compile(r"lend|credit|vault|stablecoin|tokeniz|sec |exemption|acquir|shut|wind.?down|exploit|hack|raise", re.I)
    return {c["cid"]: {"post": bool(good.search(c["title"])), "priority": 2, "duplicate": False, "reason": "stub"} for c in cands}

# ---------- Slack ----------

def slack_escape(s): return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def slack_post(text):
    url = env("SLACK_WEBHOOK_URL")
    if not url: raise RuntimeError("SLACK_WEBHOOK_URL is not set")
    unfurl = env("UNFURL", "false").lower() == "true"
    body = json.dumps({"text": text, "unfurl_links": unfurl, "unfurl_media": unfurl}).encode()
    http(url, data=body, headers={"Content-Type": "application/json"}, timeout=20)
    time.sleep(1.1)  # Slack allows about 1 message per second per webhook

# ---------- main ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print picks, do not post or save state")
    ap.add_argument("--backfill-hours", type=float, default=0, help="evaluate items from the last N hours even if already seen")
    ap.add_argument("--stub-llm", action="store_true", help="keyword stand-in for testing plumbing")
    ap.add_argument("--feeds-dir", help="read <slug>.xml fixtures from this folder instead of fetching")
    a = ap.parse_args()
    if a.backfill_hours and not a.dry_run:
        sys.exit("--backfill-hours only works with --dry-run (it would repost stories already in the channel)")

    with open(os.path.join(ROOT, "feeds.json")) as f: feeds = [x for x in json.load(f)["feeds"] if x.get("enabled", True)]
    with open(os.path.join(ROOT, "scope.md")) as f: scope = f.read()
    state = load_state()
    first_run = state is None and not a.backfill_hours
    state = state or {"seen": {}, "posted": [], "llm_failures": 0, "feed_failures": {}, "alerts": {}}
    alerts = []

    items = []
    for feed in feeds:
        try:
            if a.feeds_dir:
                slug = re.sub(r"[^a-z0-9]+", "", feed["name"].lower())
                with open(os.path.join(a.feeds_dir, slug + ".xml"), "rb") as f: raw = f.read()
            else:
                raw = http(feed["url"])
            got = parse_feed(raw, feed)
            items += got
            state["feed_failures"][feed["name"]] = 0
            log(f"{feed['name']}: {len(got)} items")
        except Exception as e:
            n = state["feed_failures"].get(feed["name"], 0) + 1
            state["feed_failures"][feed["name"]] = n
            log(f"{feed['name']}: FAILED ({n} runs) {e}")
            if n == FEED_ALERT_AFTER:
                alerts.append(f":warning: News bot: the {feed['name']} feed has failed for {n} runs in a row ({str(e)[:120]}).")

    t = now()
    max_age = float(env("MAX_AGE_HOURS", "36")) * 3600
    window = a.backfill_hours * 3600 if a.backfill_hours else max_age
    uniq = {}
    for it in items: uniq.setdefault(it["id"], it)
    cands = []
    for it in uniq.values():
        fresh = it["ts"] is not None and t - it["ts"] <= window
        if first_run or not fresh:
            state["seen"].setdefault(it["id"], t)   # too old or bootstrapping: remember, never post
        elif a.backfill_hours or it["id"] not in state["seen"]:
            cands.append(it)
    cands.sort(key=lambda c: c["ts"])
    for i, c in enumerate(cands): c["cid"] = f"c{i+1}"

    if first_run:
        log(f"First run: remembered {len(uniq)} existing items, posting nothing. New stories post from the next run.")
    log(f"{len(cands)} new candidates")

    picks = []
    if cands:
        posted_titles = [f"- {p['title']} ({p['source']})" for p in state["posted"]]
        try:
            decide = stub_decide if a.stub_llm else llm_decide
            dec = decide(cands, scope, posted_titles)
            state["llm_failures"] = 0
        except Exception as e:
            state["llm_failures"] += 1
            log(f"LLM filter FAILED ({state['llm_failures']} runs): {e}")
            if state["llm_failures"] == LLM_ALERT_AFTER:
                alerts.append(f":warning: News bot: the AI filter has failed {LLM_ALERT_AFTER} runs in a row, so nothing is posting. Last error: {str(e)[:160]}")
            dec = None
        if dec is not None:
            for c in cands:
                d = dec.get(c["cid"], {})
                keep = bool(d.get("post")) and not d.get("duplicate")
                if a.dry_run:
                    mark = "POST" if keep else "skip"
                    log(f"[{mark}] p{d.get('priority','-')} {c['source']}: {c['title']}  -- {d.get('reason','')}")
                if keep: picks.append((int(d.get("priority") or 2), c))
                else: state["seen"][c["id"]] = t
            picks.sort(key=lambda x: (x[0], x[1]["ts"]))
            cap = int(env("MAX_POSTS_PER_RUN", "8"))
            for _, c in picks[cap:]:
                # over the per-run cap: leave it unseen so the next run posts it, rather than losing it
                log(f"over cap, held for next run: {c['title']}")
            picks = [c for _, c in picks[:cap]]
            picks.sort(key=lambda c: c["ts"])

    if a.dry_run:
        log(f"{len(picks)} would post, {len(cands) - len(picks)} filtered out or held.")
        return 0

    for c in picks:
        try:
            slack_post(f"<{c['url']}|{slack_escape(c['title'])}> · {slack_escape(c['source'])}")
            state["seen"][c["id"]] = t
            state["posted"].append({"title": c["title"], "source": c["source"], "url": c["url"], "at": t})
            log(f"posted: {c['title']}")
        except Exception as e:
            log(f"Slack post failed, will retry next run: {c['title']} ({e})")
    for msg in alerts:
        try: slack_post(msg)
        except Exception as e: log(f"alert post failed: {e}")
    save_state(state)
    return 1 if state["llm_failures"] else 0

if __name__ == "__main__":
    sys.exit(main())
