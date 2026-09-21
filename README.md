# Lotus news bot

RSS -> LLM filter -> Slack. Posts crypto headlines to `#news`, one line each, and tunes
itself from the channel's 👍/👎 reactions.

## Files

- `scope.md` — editorial rules. Edit this to change what posts.
- `feeds.json` — sources. Toggle `enabled` to add/drop one.
- `newsbot.py` — the bot, stdlib only.
- `.github/workflows/newsbot.yml` — schedule + secrets wiring.

State lives on the `bot-state` branch, kept out of `main`'s history.

## Config

**Secrets:** `LLM_API_KEY`, `SLACK_BOT_TOKEN` (`xoxb-`, scopes `chat:write` + `reactions:read`), `SLACK_WEBHOOK_TEST`, `SLACK_WEBHOOK_PROD`

**Variables:** `TARGET` (`test` or `prod`), `SLACK_CHANNEL_TEST`, `SLACK_CHANNEL_PROD`, `ALERT_USER` (Slack ID to tag on failure), `PAUSED` (kill switch)

Optional: `LLM_BASE_URL` / `LLM_MODEL` (default Gemini free tier), `MAX_POSTS_PER_RUN` / `MAX_POSTS_PER_DAY` (default 2 / 8).

**Verify Slack is wired:** `gh workflow run newsbot.yml -f dry_run=false -f backfill_hours=test` — reposts the last story, log says whether the bot token or webhook carried it.

**Go live:** `gh variable set TARGET --body prod`.

## Operating

- Bot token posts as itself and reads reactions; if it fails, falls back to the webhook (post-only, no feedback loop) and alerts once.
- Feed down 12h, filter failing 3 runs, or a crash — each alerts `ALERT_USER` in Slack, at most once per 12h.
- `PAUSED=true` stops every run, no redeploy.

## Feedback loop

Reads 👍/👎 on the bot's own posts (bot-token posts only) and feeds the newest verdicts back
into the filter on every run. Needs the bot token working — the webhook fallback posts fine
but has nothing to read.

## Local test

```
python3 newsbot.py --dry-run --backfill-hours 24 [--stub-llm] [--feeds-dir <dir>]
```
