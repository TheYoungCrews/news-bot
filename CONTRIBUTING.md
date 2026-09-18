# Contributing

The bot learns from the channel. Two ways to shape it: react, or change the code.

## React in Slack

Every story posts with a footer prompt:

- **👍 relevant** / **👎 not relevant** — click to tune what gets posted. When the feedback loop is on (see below), the bot seeds both reactions so it's one click.
- **💬 reply in-thread** to flag a problem (wrong source, duplicate, bad take).
- **Tag `@claude`** in the thread to ask for a change directly.

## Change the code

- Point your own coding agent at this repo, or open a draft PR.
- Easiest win: edit [`feeds.json`](feeds.json) to add or drop a source. Flip `enabled` to pause one without deleting it.
- Editorial rules live in [`scope.md`](scope.md) — what gets posted and what gets skipped.

## Where feedback goes

👍/👎 are read back into `feedback.jsonl` (kept on the `bot-state` branch) and rolled up into a per-source score. That score is a light tie-breaker in ranking — it nudges well-received sources ahead of poorly-received ones **within the same priority**, and never overrides the model's priority call.

The ingestion loop is **opt-in**. It only runs when these are set in the GitHub Action:

- Secret `SLACK_BOT_TOKEN` — a Slack bot token with scopes `chat:write`, `reactions:write`, `reactions:read`.
- Variable `SLACK_CHANNEL_ID` — the channel to post into, e.g. `C0123456789`.

Without the token the bot posts through the webhook exactly as before; the 👍/👎 footer prompt still shows, but reactions aren't collected.
