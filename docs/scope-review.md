# scope.md size budget

`scope.md` is re-sent in full on every LLM call -- once per batch of candidates, every run.
It is the file that took the bot down on 2026-09-22: two rounds of calibration edits (plus
a separate bug that briefly stored the file's base64 encoding as its own content) pushed it
past Groq's 7,000-8,000 tokens-per-minute cap, and every filter call started failing with
HTTP 413.

**Budget: scope.md stays under 7,000 characters.** Check with `wc -c scope.md`.

## Adding a rule

If a new rule is worth adding, something else has to go. In order of preference:

1. Delete a calibration example. Rules generalize, examples don't -- and `state.feedback`
   already injects the newest real rejects/keeps into the prompt at runtime (see
   `feedback_rows`/`feedback_text` in `newsbot.py`), so the static examples in scope.md only
   need to anchor the pattern, not enumerate every past story. Cap: at most 10 examples,
   total, one line each.
2. Tighten prose on an existing rule. Entity lists (protocol/company names) are usually
   worth keeping as-is -- they're what the model pattern-matches on. Explanatory sentences
   around them are the first thing to cut.
3. Only if neither of those frees enough room: fold two overlapping rules into one.
   Don't delete a rule outright without a documented replacement -- if it's back in
   production as a Skip pattern, an example, or a merged bullet somewhere.

## Other levers, if the budget alone isn't enough

`newsbot.py` also caps two other things appended to every prompt:

- `posted_titles`: last 10 posted stories only, not the full 7-day window.
- team feedback: 8 rejects + 4 keeps (`feedback_rows`), not 15/10.

And there's a runtime guard (`PROMPT_TOKEN_BUDGET` in `llm_decide`): if the estimated
prompt size (`len(prompt)//4`) is still over ~5,500 tokens after those caps, the bot logs a
warning and drops the oldest feedback rows and posted titles until it fits, rather than
sending an oversized request and failing outright. That guard is a safety net, not a
substitute for keeping scope.md itself small -- it papers over context, it doesn't restore it.
