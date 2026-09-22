#!/usr/bin/env python3
"""Lotus #news bot: RSS -> LLM filter -> Slack (headline + link).

Standard library only, so the GitHub Actions job needs no installs.

Environment:
  SLACK_BOT_TOKEN     xoxb- bot token (chat:write, reactions:read). With SLACK_CHANNEL_ID the bot
                      posts as itself and reads team reactions on its posts
  SLACK_CHANNEL_ID    channel to post in, e.g. C0123ABCD (the bot must be invited)
  SLACK_WEBHOOK_URL   fallback: incoming webhook, posts only, cannot read reactions
  LLM_API_KEY         API key for an OpenAI-compatible chat endpoint (Gemini by default)
  LLM_BASE_URL        default https://generativelanguage.googleapis.com/v1beta/openai/
                      Claude: https://api.anthropic.com/v1   xAI: https://api.x.ai/v1
  LLM_MODEL           comma-separated, tried in order. default gemini-flash-latest,gemini-2.5-flash
  LLM_API_STYLE       openai or anthropic. Detected from LLM_BASE_URL, override only if needed
  LLM_MAX_TOKENS      reply budget, default 2500 (thinking models need room before the JSON)
  CONTACT_EMAIL       optional, added to the User-Agent (SEC asks bots to identify themselves)
  MAX_POSTS_PER_RUN   default 2
  MAX_POSTS_PER_DAY   default 8 (rolling 24h), MAX_POSTS_PER_WEEKEND_DAY default 3
  MAX_PRIORITY        highest priority number allowed through, default 2 (3 = marginal, never posts)
  DUPE_THRESHOLD      title-overlap cut for same-story detection, default 0.42
  MAX_AGE_HOURS       ignore items older than this, default 36
  ALERT_USER          Slack member ID to tag when something breaks, e.g. U01234567
  START_POSTING_AT    ISO date/time (ET) before which the bot reads feeds but posts nothing
  PAUSED              "true" to stop the bot posting at all (kill switch, no code change)
  UNFURL              "true" to let Slack unfurl links itself, default false (we build the card)
  PREVIEW             card (default) or plain, to post the bare headline + link line
  IMAGE_STYLE         large (default) or thumb
  CARD_COLOR          left bar colour, default #2FFAE2
"""
import argparse, hashlib, html, json, os, re, sys, time, traceback, urllib.error, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode, urlsplit, urlunsplit

ROOT = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(ROOT, "state", "seen.json")
EASTERN = timezone(timedelta(hours=-4))     # the team's clock, for the weekend rule
SEEN_TTL = 14 * 86400
POSTED_TTL = 7 * 86400
FEEDBACK_WINDOW = 3 * 86400   # keep checking a post for reactions this long
FEEDBACK_TTL = 90 * 86400     # remember the team's verdicts this long
UP = {"+1", "thumbsup", "white_check_mark", "heavy_check_mark", "fire", "100", "eyes", "firecracker"}
DOWN = {"-1", "thumbsdown", "x", "no_entry", "no_entry_sign", "wastebasket"}
LLM_ALERT_AFTER = 3        # consecutive failed runs before a Slack warning
FEED_ALERT_AFTER = 24      # consecutive failed runs (12h at 30 min) before a Slack warning
ALERT_COOLDOWN = 12 * 3600 # don't repeat the same warning more often than this
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
        image = ""
        for c in n:
            u = c.attrib.get("url", "")
            if local(c.tag) in ("thumbnail", "content", "enclosure") and u.startswith("http"):
                is_img = (c.attrib.get("medium") == "image"
                          or c.attrib.get("type", "").startswith("image")
                          or re.search(r"\.(jpe?g|png|webp)", u, re.I))
                if is_img:
                    image = u
                    break
        items.append({
            "id": hashlib.sha1(canonical(link).encode()).hexdigest()[:16],
            "source": feed["name"], "kind": feed.get("kind", "news"),
            "title": title, "url": link, "ts": ts,
            "categories": [c for c in cats if c][:6], "summary": summary, "image": image,
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
- priority: 1 = major (a team member would be annoyed to miss it), 2 = clearly relevant, 3 = marginal.
  Only 1 and 2 ever get posted, and the channel has room for about 5-8 posts a DAY in total, so be strict.
- Skip anything that continues a story thread already in <already_posted>, unless it adds a material new fact.
- Reply with JSON only, no prose, in this shape:
{{"decisions": [{{"id": "c1", "title_starts": "the first four words of that item's title", "post": true, "priority": 1, "duplicate": false, "reason": "under 12 words"}}]}}
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
                    if e.code in (429, 500, 502, 503, 504): time.sleep(15 * (attempt + 1)); continue
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
        out = {}
        for d in parsed.get("decisions", []):
            cid = str(d.get("id"))
            c = next((x for x in chunk if x["cid"] == cid), None)
            if not c: continue
            echo = (d.get("title_starts") or "").strip().lower()[:18]
            if echo and echo not in c["title"].lower():   # model mixed up which item it was judging
                log(f"dropping mismatched decision for {cid}: {echo!r} is not in {c['title'][:50]!r}")
                continue
            out[cid] = d
        return out

    decisions = {}
    for i in range(0, len(cands), batch):
        if i: time.sleep(float(env("LLM_PACE_SECONDS", "5")))   # stay under the free tier's per-minute budget
        chunk = cands[i:i + batch]
        got = ask(chunk)
        missing = [c for c in chunk if c["cid"] not in got]
        if missing:                      # models sometimes answer for only part of a batch
            log(f"retrying {len(missing)} candidates the model skipped")
            time.sleep(float(env("LLM_PACE_SECONDS", "5")))
            got.update(ask(missing))
            still = [c["cid"] for c in chunk if c["cid"] not in got]
            if still: log(f"no decision after retry, leaving unposted: {', '.join(still)}")
        decisions.update(got)
    return decisions

STOP = {"the","and","for","with","from","that","this","says","after","into","over","amid",
        "what","will","plans","could","more","than","its","their","about","ahead","without"}

def title_words(t):
    return {w for w in re.findall(r"[a-z0-9]{4,}", (t or "").lower()) if w not in STOP}

def title_overlap(a, b):
    """Rough same-story test: shared significant words over the shorter title."""
    wa, wb = title_words(a), title_words(b)
    if not wa or not wb: return 0.0
    return len(wa & wb) / min(len(wa), len(wb))

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

def preview_card(c):
    """Build the link preview ourselves from the feed's own title, summary and image.

    Slack's own unfurling depends on the publisher answering Slackbot; The Defiant
    (Cloudflare) returns 403, so its links would never get a card. The feed already
    carries everything a card needs, so we build it and keep unfurling off.
    """
    if env("PREVIEW", "card").lower() == "plain": return None
    card = {"color": env("CARD_COLOR", "#2FFAE2"),
            "title": c["title"], "title_link": c["url"],
            "footer": c["source"], "fallback": f"{c['title']} - {c['source']}"}
    if c.get("summary"): card["text"] = c["summary"][:280]
    if c.get("image"):
        card["thumb_url" if env("IMAGE_STYLE", "large").lower() == "thumb" else "image_url"] = c["image"]
    return card

def should_alert(state, key, t):
    """True the first time a problem shows up, then at most once every ALERT_COOLDOWN.

    Without this a broken key alerts once and then goes quiet forever, which looks
    exactly like a bot that is working.
    """
    last = state.setdefault("alerts", {}).get(key, 0)
    if t - last < ALERT_COOLDOWN: return False
    state["alerts"][key] = t
    return True

def alert(msg):
    """Post a human-readable problem report, tagging whoever owns the bot."""
    who = env("ALERT_USER")                      # a Slack member ID, e.g. U01234567
    run = ""
    if env("GITHUB_RUN_ID"):
        run = (f" | <{env('GITHUB_SERVER_URL', 'https://github.com')}/{env('GITHUB_REPOSITORY')}"
               f"/actions/runs/{env('GITHUB_RUN_ID')}|run log>")
    head = f"<@{who}> " if who else ""
    try:
        slack_post(f":warning: {head}the news bot needs a look. {msg}{run}")
    except Exception as e:
        log(f"could not post alert: {e}")

SLACK_ERRORS = []   # bot-token failures this run, reported once via alert()

def slack_ready():
    return bool((env("SLACK_BOT_TOKEN") and env("SLACK_CHANNEL_ID")) or env("SLACK_WEBHOOK_URL"))

def slack_api(method, payload=None, params=None):
    url = "https://slack.com/api/" + method
    if params: url += "?" + urlencode(params)
    headers = {"Authorization": "Bearer " + env("SLACK_BOT_TOKEN", "")}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json; charset=utf-8"
    r = json.loads(http(url, data=data, headers=headers, timeout=20))
    if not r.get("ok"):
        extra = f" (needs {r['needed']}; token has {r.get('provided') or 'none'})" if r.get("needed") else ""
        raise RuntimeError(f"Slack {method}: {r.get('error')}{extra}")
    return r

def slack_post(text, card=None):
    """Post a message. Returns (channel, ts) when posting as the bot, (None, None) via webhook."""
    unfurl = env("UNFURL", "false").lower() == "true"
    payload = {"text": text, "unfurl_links": unfurl, "unfurl_media": unfurl}
    if card: payload["attachments"] = [card]
    if env("SLACK_BOT_TOKEN") and env("SLACK_CHANNEL_ID"):
        try:
            r = slack_api("chat.postMessage", {**payload, "channel": env("SLACK_CHANNEL_ID")})
            time.sleep(1.1)
            return r["channel"], r["ts"]
        except Exception as e:
            # a bad scope or a bot missing from the channel must not go quiet: fall back and report
            SLACK_ERRORS.append(str(e))
            if not env("SLACK_WEBHOOK_URL"): raise
            log(f"bot token post failed ({e}), using the webhook instead")
    url = env("SLACK_WEBHOOK_URL")
    if not url: raise RuntimeError("no Slack destination: set SLACK_BOT_TOKEN + SLACK_CHANNEL_ID, or SLACK_WEBHOOK_URL")
    http(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, timeout=20)
    time.sleep(1.1)  # Slack allows about 1 message per second
    return None, None

def test_post():
    """Repost the last story we sent, to prove the Slack wiring. Touches no state.
    Trigger: run the workflow with dry_run off and backfill_hours set to "test"."""
    last = ((load_state() or {}).get("posted") or [None])[-1]
    c = ({"title": last["title"], "url": last["url"], "source": last["source"]} if last else
         {"title": "Lotus Newswire test post", "url": "https://github.com/TheYoungCrews/news-bot", "source": "test"})
    try:
        ch, ts = slack_post(f":test_tube: test · <{c['url']}|{slack_escape(c['title'])}> · {slack_escape(c['source'])}",
                            card=preview_card(c))
    except Exception as e:
        log(f"TEST POST FAILED on every route: {e}")
        return 1
    if ch:
        log(f"TEST POST OK via the bot token, channel {ch}. Reactions will be read.")
        return 0
    if SLACK_ERRORS:
        log(f"TEST POST went out via the webhook because the bot token was rejected: {SLACK_ERRORS[0]}")
        return 1
    log("TEST POST OK via the webhook (no bot token set, so reactions will not be read)")
    return 0

def repost_story(match):
    """Repost an already-posted story to the channel this run resolves to (real card, not a
    test post) -- for pushing a good pick into a channel it didn't originally go to, like the
    first story into #news right after a TARGET switch. Matches by title substring, most
    recent first. Updates that story's ch/ts so feedback tracking follows the new message.

    state.posted only keeps title/source/url, not image/summary, so this re-fetches the
    source feed and looks the story up by URL to rebuild the full card. Falls back to a
    bare title/link card if the feed fetch fails or the item has aged out of it.
    """
    state = load_state()
    hit = next((p for p in reversed((state or {}).get("posted", [])) if match.lower() in p["title"].lower()), None)
    if not hit:
        log(f"no posted story matching {match!r}")
        return 1
    c = {"title": hit["title"], "url": hit["url"], "source": hit["source"]}
    with open(os.path.join(ROOT, "feeds.json")) as f:
        feed_cfg = next((x for x in json.load(f)["feeds"] if x["name"] == hit["source"]), None)
    if feed_cfg:
        try:
            fresh = next((it for it in parse_feed(http(feed_cfg["url"]), feed_cfg) if canonical(it["url"]) == canonical(hit["url"])), None)
            if fresh: c = fresh
            else: log("story not found in the current feed, reposting without image/summary")
        except Exception as e:
            log(f"could not refresh the card, reposting without image/summary: {e}")
    try:
        ch, ts = slack_post(f"<{c['url']}|{slack_escape(c['title'])}> · {slack_escape(c['source'])}", card=preview_card(c))
    except Exception as e:
        log(f"repost failed: {e}")
        return 1
    if ch:
        hit["ch"], hit["ts"] = ch, ts
        save_state(state)
    log(f"reposted: {hit['title']} -> channel {ch or '(webhook)'}")
    return 0

def collect_feedback(state, t):
    """Read the team's thumbs up/down on our recent posts and remember the verdicts."""
    fb = state.setdefault("feedback", {})
    if env("SLACK_BOT_TOKEN"):
        for p in state["posted"]:
            if not p.get("ts") or t - p["at"] > FEEDBACK_WINDOW: continue
            try:
                r = slack_api("reactions.get", params={"channel": p["ch"], "timestamp": p["ts"]})
            except Exception as e:
                log(f"could not read reactions, skipping feedback this run: {e}")
                break
            up = down = 0
            for rx in r.get("message", {}).get("reactions", []):
                name = rx["name"].split("::")[0]          # "+1::skin-tone-3" -> "+1"
                if name in UP: up += rx["count"]
                elif name in DOWN: down += rx["count"]
            if up or down:
                fb[p["url"]] = {"title": p["title"], "source": p["source"], "up": up, "down": down, "at": p["at"]}
    for k in [k for k, v in fb.items() if t - v["at"] > FEEDBACK_TTL]: del fb[k]

def feedback_block(state):
    """Recent team verdicts, appended to the scope so the filter learns from them every run."""
    fb = sorted(state.get("feedback", {}).values(), key=lambda v: -v["at"])
    bad = [v for v in fb if v["down"] > v["up"]][:15]
    good = [v for v in fb if v["up"] > v["down"]][:10]
    if not bad and not good: return ""
    out = ["", "", "## Team feedback from the channel (newest first; this outranks the examples above)"]
    if bad:
        out.append("The team thumbed these DOWN. Skip stories like them:")
        out += [f"- {v['title']} ({v['source']})" for v in bad]
    if good:
        out.append("The team thumbed these UP. Post more like them:")
        out += [f"- {v['title']} ({v['source']})" for v in good]
    return "\n".join(out)

# ---------- main ----------

def _run():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print picks, do not post or save state")
    ap.add_argument("--backfill-hours", type=float, default=0, help="evaluate items from the last N hours even if already seen")
    ap.add_argument("--stub-llm", action="store_true", help="keyword stand-in for testing plumbing")
    ap.add_argument("--feeds-dir", help="read <slug>.xml fixtures from this folder instead of fetching")
    ap.add_argument("--repost", help="repost an already-posted story (matched by title substring) to this run's channel")
    a = ap.parse_args()
    if a.backfill_hours and not a.dry_run:
        sys.exit("--backfill-hours only works with --dry-run (it would repost stories already in the channel)")

    if env("PAUSED", "").lower() in ("1", "true", "yes"):
        # kill switch: set the PAUSED repo variable to stop posting without touching code
        log("PAUSED is set, doing nothing this run")
        return 0

    if env("BACKFILL_HOURS", "").strip().lower() == "test" and not a.dry_run:
        return test_post()

    if a.repost:
        return repost_story(a.repost)

    start_at = env("START_POSTING_AT")           # e.g. 2026-09-21T08:00 (ET); quiet until then
    holding = False
    if start_at and not a.dry_run:
        try:
            when = datetime.fromisoformat(start_at)
            if when.tzinfo is None: when = when.replace(tzinfo=EASTERN)
            holding = now() < when.timestamp()
            if holding: log(f"holding until {start_at}: reading feeds, posting nothing")
        except ValueError:
            log(f"START_POSTING_AT is not a date I understand: {start_at!r}")

    if not a.dry_run and not slack_ready():
        # nowhere to post yet (Slack app still pending): don't burn model calls on items we can't deliver
        log("no Slack destination is set, skipping this run")
        return 0

    with open(os.path.join(ROOT, "feeds.json")) as f: feeds = [x for x in json.load(f)["feeds"] if x.get("enabled", True)]
    with open(os.path.join(ROOT, "scope.md")) as f: scope = f.read()
    state = load_state()
    first_run = (state is None and not a.backfill_hours) or holding
    state = state or {"seen": {}, "posted": [], "llm_failures": 0, "feed_failures": {}, "alerts": {}}
    alerts = []
    t = now()

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
            if n >= FEED_ALERT_AFTER and should_alert(state, "feed:" + feed["name"], t):
                alerts.append(f"The {feed['name']} feed has been failing for {n} runs "
                              f"(about 12 hours). Other sources are still posting. Error: {str(e)[:140]}")

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
        log(f"Remembered {len(uniq)} existing items, posting nothing this run.")
    log(f"{len(cands)} new candidates")

    if not a.dry_run: collect_feedback(state, t)
    picks = []
    if cands:
        posted_titles = [f"- {p['title']} ({p['source']})" for p in state["posted"]]
        try:
            decide = stub_decide if a.stub_llm else llm_decide
            dec = decide(cands, scope + feedback_block(state), posted_titles)
            state["llm_failures"] = 0
        except Exception as e:
            state["llm_failures"] += 1
            log(f"LLM filter FAILED ({state['llm_failures']} runs): {e}")
            if state["llm_failures"] >= LLM_ALERT_AFTER and should_alert(state, "llm", t):
                alerts.append(f"The filter has failed {LLM_ALERT_AFTER} runs in a row, so nothing is posting "
                              f"and stories are queueing up. Usually a bad or rate-limited model key. "
                              f"Error: {str(e)[:160]}")
            dec = None
        if dec is not None:
            for c in cands:
                d = dec.get(c["cid"], {})
                keep = bool(d.get("post")) and not d.get("duplicate")
                if a.dry_run:
                    mark = "POST" if keep else "skip"
                    log(f"[{mark}] p{d.get('priority','-')} {c['source']}: {c['title']}  -- {d.get('reason','')}")
                pr = int(d.get("priority") or 2)
                if keep and pr > int(env("MAX_PRIORITY", "2")):
                    log(f"priority {pr}, below the bar: {c['title']}")
                    keep = False
                if keep: picks.append((pr, c))
                else: state["seen"][c["id"]] = t
            picks.sort(key=lambda x: (x[0], x[1]["ts"]))
            # the model only sees one batch at a time, so catch duplicates across batches here
            deduped = []
            for _, c in picks:
                twin = next((k for k in deduped
                             if title_overlap(c["title"], k["title"]) >= float(env("DUPE_THRESHOLD", "0.42"))), None)
                if twin:
                    log(f"same story as {twin['source']}'s, dropping: {c['title']}")
                    state["seen"][c["id"]] = t
                    continue
                deduped.append(c)
            # don't repeat a story we already posted in the last week
            recent = [p["title"] for p in state["posted"]]
            fresh = []
            for c in deduped:
                twin = next((r for r in recent if title_overlap(c["title"], r) >= float(env("DUPE_THRESHOLD", "0.42"))), None)
                if twin:
                    log(f"already covered this week, dropping: {c['title']}")
                    state["seen"][c["id"]] = t
                    continue
                fresh.append(c)
            deduped = fresh

            # daily budget: weekends are quieter, and a single run never floods the channel
            weekend = datetime.fromtimestamp(t, timezone.utc).astimezone(EASTERN).weekday() >= 5
            day_cap = int(env("MAX_POSTS_PER_WEEKEND_DAY", "3") if weekend else env("MAX_POSTS_PER_DAY", "8"))
            posted_today = sum(1 for p in state["posted"] if t - p["at"] < 86400)
            room = max(0, day_cap - posted_today)
            if room < len(deduped):
                log(f"daily budget: {posted_today}/{day_cap} posted in the last 24h, room for {room}")
            deduped = deduped[:room]

            cap = int(env("MAX_POSTS_PER_RUN", "2"))
            for c in deduped[cap:]:
                # over the per-run cap: leave it unseen so the next run posts it, rather than losing it
                log(f"over cap, held for next run: {c['title']}")
            picks = deduped[:cap]
            picks.sort(key=lambda c: c["ts"])

    if a.dry_run:
        log(f"{len(picks)} would post, {len(cands) - len(picks)} filtered out or held.")
        return 0

    failed = 0
    for c in picks:
        try:
            ch, ts = slack_post(f"<{c['url']}|{slack_escape(c['title'])}> · {slack_escape(c['source'])}",
                                card=preview_card(c))
            state["seen"][c["id"]] = t
            state["posted"].append({"title": c["title"], "source": c["source"], "url": c["url"],
                                    "at": t, "ch": ch, "ts": ts})
            log(f"posted: {c['title']}")
        except Exception as e:
            failed += 1
            log(f"Slack post failed, will retry next run: {c['title']} ({e})")
    if SLACK_ERRORS and should_alert(state, "slack-token", t):
        alerts.append(f"Slack rejected the bot token (`{SLACK_ERRORS[0][:100]}`), so posts are going through "
                      f"the webhook and team reactions are not being read. Usually a missing scope that needs "
                      f"admin approval, or the bot is not in the channel.")
    for msg in alerts:
        alert(msg)
    save_state(state)
    return 1 if state["llm_failures"] or failed else 0

def main():
    """Never let a crash be silent: GitHub turns the run red, Slack gets a name to tag."""
    try:
        return _run()
    except SystemExit:
        raise
    except Exception as e:
        log(traceback.format_exc())
        alert(f"The run crashed before posting anything: `{type(e).__name__}: {str(e)[:200]}`")
        return 1

if __name__ == "__main__":
    sys.exit(main())
