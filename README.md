# Lotus news bot

Posts filtered crypto news to `#news` as `headline + link · source`, and learns from the
channel's 👍/👎 reactions on its own posts.

## How it works

```
every run:  GitHub Actions job (business hours: every 15 min; overnight/weekends: every 2h)
                    |
                    v
   RSS feeds (CoinDesk, The Block, The Defiant, SEC)
                    |  drop anything already seen or over 36h old
                    v
   one API call per batch: here are up to 12 new headlines, here is scope.md
                 (plus recent team reactions), here is what we posted recently. Which ones?
                    |  model replies with JSON: post / skip / duplicate, plus a priority
                    v
   dedupe + daily/per-run caps
                    |
                    v
   Slack, as the bot (chat.postMessage) if the bot token works, else an incoming webhook  ->  #news
                    |
                    v
   next run: read 👍/👎 on posts from the last 3 days (bot-token posts only) -> fed back into the next filter call
```

The feeds are the input and Slack is the output. The model sits in the middle as the judge and touches nothing else: it reads headlines and returns a yes or no for each. Swapping models changes two environment variables and nothing else in the pipeline.

Sources are CoinDesk, The Block, The Defiant, and SEC press releases (crypto items only, per the rule in `scope.md`). Unchained, Cointelegraph and Decrypt are in `feeds.json`, disabled.

Cost: about 1,440 of the 2,000 free Actions minutes a private repo gets each month, plus whatever the model provider charges. On Gemini's free tier that is $0. See the model table below.

## Files

| File | What it does | Edit it when |
|---|---|---|
| `scope.md` | Plain-English rules for what gets posted | The channel is too noisy or missing things |
| `feeds.json` | Sources. Flip `enabled` to pause one | Adding or dropping a source |
| `newsbot.py` | Fetch, filter, dedupe, post. Standard library only | Rarely |
| `.github/workflows/newsbot.yml` | Schedule and secrets wiring | Changing how often it runs |

State (what has been seen and posted) lives on a separate `bot-state` branch so `main` history stays clean.

## Setup (about 20 minutes)

### 1. Model API key

Pick one. Volume is roughly 1.25M input and 30k output tokens a month.

| Provider | `LLM_BASE_URL` | `LLM_MODEL` | Monthly cost |
|---|---|---|---|
| Gemini (default) | leave unset | leave unset | $0 |
| Claude | `https://api.anthropic.com/v1` | `claude-haiku-4-5` | about $1.50 |
| Claude, better judgment | `https://api.anthropic.com/v1` | `claude-sonnet-5` | about $3 |
| xAI Grok | `https://api.x.ai/v1` | current id from the xAI console | about $3 |
| Groq | `https://api.groq.com/openai/v1` | `openai/gpt-oss-20b,llama-3.1-8b-instant` | $0 on the free tier |

The script detects the Claude API from its base URL and uses the native Messages endpoint. Everything else goes through the OpenAI-compatible path, which Gemini, xAI, Groq and OpenRouter all support.

**For Gemini:** go to https://aistudio.google.com/apikey and click **Create API key** in a new project. Do not link a billing account to that project. Without billing it stays on the free tier and cannot be charged. Free-tier prompts may be used by Google to improve its products, and the bot sends public headlines plus `scope.md`.

**For Groq:** sign up at https://console.groq.com with your work Google account, create an API key, and set `LLM_BASE_URL` and `LLM_MODEL` as repo variables in step 3. The free tier needs no card; a payment method is only required to go beyond it.

**For Claude or xAI:** create a key in the provider console, add credits, and set `LLM_BASE_URL` and `LLM_MODEL` as repo variables in step 3.

Note: Google Cloud asks for card details before it will create a project on a Workspace account, so the Gemini free tier is only realistic on a consumer Google account or once an admin provisions a Cloud project.

### 2. Slack app: bot token + a fallback webhook

The bot posts as itself (`chat.postMessage`) when it has a bot token, so it can read the
channel's reactions back. If the token is missing or gets rejected, it falls back to an
incoming webhook, which can post but can't read anything back.

1. Go to https://api.slack.com/apps, then **Create New App**, **From scratch**. Name it
   `News Bot` and pick your workspace.
2. **OAuth & Permissions** > **Bot Token Scopes**: add `chat:write` and `reactions:read`.
3. **Install to Workspace** (or **Reinstall**, if scopes changed after installing). If the
   workspace requires admin approval, request it here.
4. Copy the **Bot User OAuth Token** (`xoxb-...`) — this goes in the `SLACK_BOT_TOKEN`
   secret below. Do not use the User OAuth Token (`xoxp-...`); that's a different token
   with different scopes.
5. Invite the bot to the channel(s) it posts in: `/invite @News Bot`.
6. Also set up **Incoming Webhooks** (turn it on, **Add New Webhook**, pick a channel) as
   a fallback for when the bot token isn't working yet, or gets revoked. Create one webhook
   per channel you use (test and prod).

### 3. GitHub repo
1. Create a **private** repo, for example `news-bot`.
2. Push these files. With git: `git init && git add . && git commit -m init && git branch -M main && git remote add origin <repo-url> && git push -u origin main`. If you upload in the browser instead, make sure the hidden `.github/workflows/newsbot.yml` file makes it in (Finder hides folders that start with a dot; press Cmd+Shift+. to show them).
3. In **Settings > Secrets and variables > Actions**, add these **secrets**:
   - `LLM_API_KEY`: the model provider key from step 1
   - `SLACK_BOT_TOKEN`: the `xoxb-` token from step 2
   - `SLACK_WEBHOOK_TEST` / `SLACK_WEBHOOK_PROD`: the webhook URLs from step 2, one per channel
4. And these **variables**:
   - `TARGET`: `test` (default) posts to `SLACK_WEBHOOK_TEST` / `SLACK_CHANNEL_TEST`; `prod`
     switches to `SLACK_WEBHOOK_PROD` / `SLACK_CHANNEL_PROD`. If `TARGET=prod` but the prod
     secret isn't set, it silently falls back to test — never to `#news` by accident.
   - `SLACK_CHANNEL_TEST` / `SLACK_CHANNEL_PROD`: the channel IDs the bot token posts into
     (Slack channel details > channel ID at the bottom). The bot must be invited to both.
   - `ALERT_USER`: your Slack member ID (Slack profile > **...** > Copy member ID). Tagged
     when something breaks.
   - `CONTACT_EMAIL`: added to the bot's User-Agent. SEC.gov asks automated clients to identify themselves.
   - `LLM_BASE_URL` and `LLM_MODEL`: only if you are not using Gemini. `LLM_MODEL` takes a comma-separated list and falls back in order.
   - `PAUSED`: `true` stops every run immediately (kill switch, no code change, no redeploy).
   - `UNFURL`: set `true` to show link previews. Off by default to keep the channel compact.
   - `MAX_POSTS_PER_RUN` / `MAX_POSTS_PER_DAY` / `MAX_POSTS_PER_WEEKEND_DAY`: safety caps, defaults 2 / 8 / 3.

### 4. Verify the Slack wiring
Run the workflow with **Dry run** unchecked and **backfill_hours** set to `test`. This
reposts the last story sent (or a placeholder, on a fresh setup), touches no state, and the
log says which route it used:
```
gh workflow run newsbot.yml -f dry_run=false -f backfill_hours=test
```
- `TEST POST OK via the bot token` — reactions will be read, the feedback loop is live.
- `...via the webhook because the bot token was rejected: ...` — names the missing scope.
  Fix the token in Slack (step 2) and try again.

### 5. Check the filter before anything posts
1. Go to **Actions > news-bot > Run workflow**. Leave **Dry run** checked and set **backfill_hours** to `24`.
2. Open the run log. Each item shows `[POST]` or `[skip]` with a short reason. If the picks look wrong, edit `scope.md` and run it again.

### 6. Go live in the test channel
1. Run the workflow once with **Dry run** unchecked and backfill `0`. The first live run only records existing items and posts nothing, so the channel doesn't get flooded.
2. From then on the schedule posts new stories automatically (business hours: every 15 min; overnight and weekends: every 2h). GitHub's scheduler can run late, especially overnight.
3. After a few days of reasonable output in the test channel, run `gh variable set TARGET --body prod` to switch to `#news`.

## When something breaks

- **The model filter fails 3 runs in a row** (bad key, quota, model retired): the bot posts a warning in the channel, and items wait to be retried. To swap models, set `LLM_MODEL`.
- **A feed fails for 24 runs** (about 12 hours): the bot posts a warning naming the feed.
- **The bot token gets rejected**: the bot falls back to the webhook, posts a warning naming the missing scope, and reactions stop being read until it's fixed.
- **Any crash**: caught, logged, and alerted — a run never fails silently.
- Alerts repeat at most once every 12 hours per problem, and always tag `ALERT_USER`.
- **Failed runs** also show a red X in the Actions tab, and GitHub emails the person who set up the schedule.
- **Kill switch:** set the `PAUSED` variable to `true` to stop every run instantly, no redeploy needed.

## Feedback loop

Every non-dry run, the bot reads 👍/👎 reactions on its own posts from the last 3 days
(bot-token posts only — the webhook can't return a message ID to react to) and remembers
the verdicts for 90 days. The 15 newest thumbs-down and 10 newest thumbs-up titles get
appended to `scope.md` on every filter call, marked as outranking the written examples. So
the fastest way to steer the bot day to day is reacting in Slack, not editing `scope.md`.

This needs the bot token working (step 4) — with the webhook fallback it posts fine but the
loop has nothing to read. Thread replies and stories the bot missed entirely aren't
captured (would need the `channels:history` scope); for now those go to Crews by DM.

## Tuning

- **Too noisy:** add the offending pattern to the Skip list in `scope.md`, or lower the bar sentence ("A good day is 5 to 15 posts").
- **Missing things:** add the topic or company names to the Post list.
- **Another outlet:** add it to `feeds.json`. Cointelegraph and Decrypt are already there, disabled. They add volume and mostly repeat what's already covered.
- **Minutes running short** (other private repos in the account also use Actions): thin out the cron in the workflow, e.g. drop the 15-minute weekday slots to 30.
- **Switch model:** change `LLM_BASE_URL` and `LLM_MODEL` per the table above, and replace the `LLM_API_KEY` secret. Groq's free tier also works: `LLM_BASE_URL=https://api.groq.com/openai/v1`.

## Local testing

```
python3 newsbot.py --dry-run --backfill-hours 24        # real filter, needs LLM_API_KEY
python3 newsbot.py --dry-run --backfill-hours 24 --stub-llm   # keyword stand-in, checks plumbing only
```

Add `--feeds-dir <dir>` to read local fixtures instead of fetching live feeds — save each
feed's raw XML as `<dir>/coindesk.xml`, `theblock.xml`, `thedefiant.xml`, `sec.xml` (fixtures
aren't checked into the repo).
