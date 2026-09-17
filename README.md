# Lotus news bot

Posts filtered crypto news to Slack as `headline + link · source`.

## How it works

```
every 30 min:  GitHub Actions job
                    |
                    v
   RSS feeds (CoinDesk, The Block, The Defiant, SEC)
                    |  drop anything already seen
                    v
   one API call: here are 3 new headlines, here is scope.md,
                 here is what we posted recently. Which ones?
                    |  model replies with JSON: post / skip / duplicate
                    v
   Slack incoming webhook  ->  #news
```

The feeds are the input and Slack is the output. The model sits in the middle as the judge and touches nothing else: it reads headlines and returns a yes or no for each. One call per run, and no call at all when no new items came in. Swapping models changes two environment variables and nothing else in the pipeline.

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

The script detects the Claude API from its base URL and uses the native Messages endpoint. Everything else goes through the OpenAI-compatible path, which Gemini, xAI, Groq and OpenRouter all support.

**For Gemini:** go to https://aistudio.google.com/apikey and click **Create API key** in a new project. Do not link a billing account to that project. Without billing it stays on the free tier and cannot be charged. Free-tier prompts may be used by Google to improve its products, and the bot sends public headlines plus `scope.md`.

**For Claude or xAI:** create a key in the provider console, add credits, and set `LLM_BASE_URL` and `LLM_MODEL` as repo variables in step 3.

### 2. Slack webhook
1. Create a test channel, for example `#news-bot-test`.
2. Go to https://api.slack.com/apps, then **Create New App**, **From scratch**. Name it `News Bot` and pick lotus-labs-workspace.
3. Open **Incoming Webhooks**, turn it on, click **Add New Webhook**, and choose `#news-bot-test`. If your workspace requires admin approval, request it here.
4. Copy the webhook URL.

### 3. GitHub repo
1. Create a **private** repo, for example `news-bot`.
2. Push these files. With git: `git init && git add . && git commit -m init && git branch -M main && git remote add origin <repo-url> && git push -u origin main`. If you upload in the browser instead, make sure the hidden `.github/workflows/newsbot.yml` file makes it in (Finder hides folders that start with a dot; press Cmd+Shift+. to show them).
3. In **Settings > Secrets and variables > Actions**, add two **secrets**:
   - `SLACK_WEBHOOK_URL`: the webhook from step 2
   - `LLM_API_KEY`: the Gemini key from step 1
4. Optional **variables** on the same page:
   - `CONTACT_EMAIL`: added to the bot's User-Agent. SEC.gov asks automated clients to identify themselves.
   - `LLM_BASE_URL` and `LLM_MODEL`: only if you are not using Gemini. `LLM_MODEL` takes a comma-separated list and falls back in order.
   - `MAX_POSTS_PER_RUN`: defaults to 8, a safety cap
   - `UNFURL`: set `true` to show link previews. Off by default to keep the channel compact.

### 4. Check the filter before anything posts
1. Go to **Actions > news-bot > Run workflow**. Leave **Dry run** checked and set **backfill_hours** to `24`.
2. Open the run log. Each item shows `[POST]` or `[skip]` with a short reason. If the picks look wrong, edit `scope.md` and run it again.

### 5. Go live in the test channel
1. Run the workflow once with **Dry run** unchecked and backfill `0`. The first live run only records existing items and posts nothing, so the channel doesn't get flooded.
2. From then on the schedule posts new stories every 30 minutes. GitHub's scheduler can run 5 to 20 minutes late.
3. After a few days of reasonable output, add a second webhook for `#news` in the Slack app and replace `SLACK_WEBHOOK_URL`.

## When something breaks

- **The model filter fails 3 runs in a row** (bad key, quota, model retired): the bot posts a warning in the channel, and items wait to be retried. To swap models, set `LLM_MODEL`.
- **A feed fails for 12 hours**: the bot posts a warning naming the feed.
- **Failed runs** also show a red X in the Actions tab, and GitHub emails the person who set up the schedule.

## Tuning

- **Too noisy:** add the offending pattern to the Skip list in `scope.md`, or lower the bar sentence ("A good day is 5 to 15 posts").
- **Missing things:** add the topic or company names to the Post list.
- **Another outlet:** add it to `feeds.json`. Cointelegraph and Decrypt are already there, disabled. They add volume and mostly repeat what's already covered.
- **Minutes running short** (other private repos in the account also use Actions): change the cron in the workflow to `7 * * * *` (hourly).
- **Switch model:** change `LLM_BASE_URL` and `LLM_MODEL` per the table above, and replace the `LLM_API_KEY` secret. Groq's free tier also works: `LLM_BASE_URL=https://api.groq.com/openai/v1`.

## Local testing

```
python3 newsbot.py --dry-run --backfill-hours 24        # real filter, needs LLM_API_KEY
python3 newsbot.py --dry-run --backfill-hours 24 --stub-llm   # keyword stand-in, checks plumbing only
```
