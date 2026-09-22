# scope.md: sharpen, don't grow

`scope.md` is re-sent in full on every LLM call -- once per batch of candidates, every run.
It's the file that took the bot down on 2026-09-22: repeated calibration edits (plus a
separate bug that briefly stored the file's base64 encoding as its own content) pushed it
past Groq's 7,000-8,000 tokens-per-minute cap, and every filter call started failing with
HTTP 413.

**Budget: scope.md stays well under 7,000 characters.** Not "at" the budget -- comfortably
under it, so normal editing doesn't need a rescue trim. Check with `wc -c scope.md`. As of
2026-09-22 it's ~5,800.

## The rule for every future edit, including the automated review

Feedback over time should make scope.md **more precise, not longer.** The file's size
should trend flat or down, never up, even as more feedback comes in. Concretely:

1. **A repeated feedback pattern almost always means an existing rule is worded too loosely
   or too tightly -- fix that rule's wording.** Don't add a new bullet, and don't add a new
   calibration example, for something an existing Tier 1/2/Skip bullet already covers in
   spirit. Tighten the bullet itself until it covers the real pattern precisely. This is the
   default action, not a fallback.
2. **Calibration examples are a fixed, small anchor set -- replace, never add.** `state.feedback`
   already injects the newest real rejects/keeps into the prompt at runtime (see
   `feedback_rows`/`feedback_text` in `newsbot.py`), so the static examples in scope.md only
   need to anchor the two or three most enduring, hardest-to-phrase-as-a-rule patterns (e.g.
   "an official talking is not an action"). Hard cap: 4 examples, total, one line each. If a
   new one is worth adding, delete the weakest one first -- the count must not grow.
3. **A genuinely novel category** (not a wording gap in an existing rule) is the only case
   for a new bullet, and it must be paid for: cut prose or merge an overlapping bullet
   elsewhere so the file's total size doesn't grow. See the 2026-09-22 consolidation of four
   near-duplicate "routine no-volume pilot" bullets into one as the model -- same coverage,
   fewer tokens, because it named the actual shared pattern instead of enumerating cases.
4. **Never delete coverage silently.** If a rule genuinely no longer applies, remove it and
   say so in the commit message -- don't just let it quietly vanish in a "trim."
5. **Entity/protocol name lists are not prose.** They're what the model pattern-matches
   obscure names against (a curator like "kpk" isn't recognizable without the list). Don't
   cut them to hit a budget -- that's a coverage loss, not a trim. Find the size savings in
   sentences, not names.

## Other things capped on every prompt

`newsbot.py` also caps what gets appended around scope.md:

- `posted_titles`: last 10 posted stories only, not the full 7-day window.
- team feedback: 8 rejects + 4 keeps (`feedback_rows`), not 15/10.
- the `PROMPT` wrapper text and per-candidate `summary` length are themselves kept short --
  they're resent on every single call too, not just scope.md.

And there's a runtime guard (`PROMPT_TOKEN_BUDGET` in `llm_decide`): if the estimated
prompt size (`len(prompt)//4`) is still over ~5,500 tokens after those caps, the bot logs a
warning and drops the oldest feedback rows and posted titles until it fits, rather than
sending an oversized request and failing. That guard is a safety net for a spike, not a
substitute for keeping scope.md itself small and sharp -- it papers over bloat, it doesn't
prevent it.
