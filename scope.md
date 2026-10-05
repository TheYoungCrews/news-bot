
# What belongs in #news

Plain English, edited by hand. The filter reads this file every run, so changing a line here changes what posts. No code changes needed.

## Who is reading

The Lotus Labs team: an institutional onchain credit market, pre-launch. BTC/ETH balance-sheet borrowing first, RWA credit next with Cicada Partners as first vault manager. Thesis: the "missing middle" of DeFi credit, between isolated pools and pooled risk, priced probabilistically. Readers already follow crypto Twitter closely -- a story earns a post only if it'd change a decision, pitch, risk assumption or competitive read this week.

Room for 5-8 posts a DAY, fewer at weekends. Flooding the channel is the main way this bot fails.

## Tier 1, always post

- **Credit venue events.** Launches, major versions, shutdowns, migrations or governance changes at: Aave, Morpho, Euler, Spark, Sky, Compound, Fluid, Maple, Gearbox, Notional, Term, Ajna, Tenor, Silo, Kamino, Seamless, Summer.fi.
- **Structured and fixed-rate credit.** Tranching, senior/junior debt, fixed-rate lending, credit ratings for onchain borrowers, undercollateralized/institutional lending desks moving onchain. Lotus's own category -- bar is low.
- **Exploits and risk events in lending.** Oracle manipulation, bad collateral, liquidation failures, curated vault losses, depegs, peg breaks. Mechanism matters more than loss size.
- **Curators and risk managers.** Gauntlet, Steakhouse, Re7, kpk, Block Analitica, Sentora, IntoTheBlock, Credora, RedStone, Chaos Labs, MEV Capital, Veda, YO, Superform, vaults.fyi. New mandates, blowups, methodology fights, consolidation, accountability.
- **Regulation touching lending, vaults, curators, stablecoins or tokenized securities.** SEC, CFTC, OCC, Fed, Treasury, Congress: rules, exemptions, no-action relief, enforcement, a securities-status statement. A finalized action, not a plan, priority or prediction about one -- those are Executive talk (Skip).
- **Partners and close orbit.** Cicada Partners, Block Analitica, Maven11, FalconX, Credora, RedStone, Arbitrum, Cyfrin.
- **M&A and funding** in credit, risk, vault or security infra, any acquirer; ~$10M+ in DeFi, any size in onchain credit/risk/insurance.

## Tier 2, post if it's substantive

- **Stablecoins and yield-bearing dollars.** Circle, Tether, Ethena, Sky, Paxos, Agora, Falcon, Resolv, Midas: launches, reserve changes, yield mechanics, a bank/fintech issuing its own stablecoin, stablecoin legislation.
- **RWA and tokenization.** BlackRock, Franklin Templeton, WisdomTree, Apollo, Hamilton Lane, Ondo, Superstate, Securitize, Centrifuge, Grove, Midas: launches, new funds, material plumbing changes (DTCC, Nasdaq).
- **Institutions arriving onchain.** Banks/brokers/exchanges/asset managers launching lending, custody, settlement, stablecoin or tokenization products, or own chains, with real volume/mechanism: Coinbase, Kraken, Robinhood, Anchorage, Galaxy, Citadel, JPMorgan, Fidelity, Nasdaq. Not a pilot -- see Skip.
- **Onchain insurance and security.** Nexus Mutual, Firelight, OpenZeppelin, Sherlock, Code4rena, Certora, Cyfrin, Chainlink, Pyth: new coverage/audit/oracle products, acquisitions, incidents, risk-relevant oracle changes. Not a feature update with no risk angle -- see Skip.
- **Original research** on credit market structure, vault risk, liquidation or lending mechanism design, including from the protocols themselves.

## Skip

- Prices, market recaps, "BTC hits X", liquidation tallies, ETF flows, derivatives positioning, "analyst says", technical analysis, predictions.
- Macro/tradfi: Fed decisions, rate moves, equities, jobs numbers, oil -- even tied to crypto prices.
- Memecoins, NFTs, gaming, celebrity/politician tokens, launchpads, airdrops, points, exchange listings.
- Bitcoin mining, corporate BTC treasury buys, reserve bills.
- Reaction/commentary once the underlying story has posted. One post per story.
- Roundups, newsletters, podcasts, opinion columns, sponsored posts, small-project press releases.
- Crime/courts, individuals, no DeFi mechanism: scams, arrests, ransom, gambling charges, CEX hacks.
- Executive talk: "X says", interviews, remarks, predictions or plans -- includes analyst/VC commentary or rankings about named companies ("X leads the Y race"), even Tier 1/2 names. The action, not the take.
- Leadership hires/departures, even at Tier 1. Exception: hiring that's itself the news (a new desk).
- ETFs as products: launches, flows, splits, AUM, ticker changes. Exception: a fund itself tokenized/onchain.
- Procedural regulatory steps (review, comment period, agenda item, vote, preliminary approval, a proposal). Post when final, not each step.
- More coverage of a thread posted this week without a material new fact. One post per story/week.
- Chain/bridge infra with no credit or risk angle: L2 upgrades, cross-chain throughput/feature updates, client releases -- even from named security vendors.
- Routine no-volume integration/pilot news: reselling someone else's stablecoin as "regulated issuer"; an RWA player "joining" another's rails; a bank consortium's deposit pilot, a single bank's first digital bond, or a card network's stablecoin rail; a central bank's own tokenization pilot. Proof-of-concept, constant. Exceptions: the issuer launching/changing it, billions-scale volume, a new mechanism, or private plumbing (DTCC, Nasdaq) -- Tier 2.

## SEC press releases

Post only crypto/digital-asset/tokenization items. Skip proxy rules, accounting, non-crypto enforcement, staffing.

## Calibration examples

Fixed anchor set -- replace, don't add, if one goes stale.

Post: "SEC rolls out 'innovation exemption' for tokenized securities venues" (regulatory action)

Skip: "Fed raises rates 25bp" (macro) · "Ava Labs president says NYSE tested Avalanche for tokenization" (executive talk)

<!-- review-log -->
## Review log

Not sent to the model (`newsbot.py` strips everything from the `<!-- review-log -->` marker
down before building the filter prompt) -- scope.md is resent on every LLM call, and this
table only grows, so it can't be in the budget `docs/scope-review.md` enforces. Append one
row a week; the bot's own Monday Slack recap has the posts/up/down counts to copy in.

| Date | Posts | Up/Down | What changed |
|---|---|---|---|
| 2026-09-17 | n/a | n/a | scope.md written; content guidelines drafted and revised |
| 2026-09-18 | n/a | n/a | Refined posting guidelines |
| 2026-09-21 | n/a | n/a | Tightened the stablecoin-distribution skip rule; calibrated from a backfill review (RWA plumbing, ECB macro, analyst takes, exec hires) |
| 2026-09-22 | n/a | n/a | Tightened around that day's downvotes, then an outage: a bug stored the file's own base64 encoding as its content, pushing scope.md past Groq's 7-8K TPM limit -- every filter call failed with HTTP 413. Fixed same day, cut 11,045 -> 5,844 chars |
| 2026-09-25 | 2 | 0 up / 2 down | The Block's and The Defiant's Fed stablecoin-capital stories both posted and got thumbs down -- a duplicate the title-overlap check missed (0.29 vs the 0.42 cutoff). Fixed 2026-10-02 with a same-day + shared-entity check |
| 2026-09-26 | n/a | n/a | Tightened "named-official statements" wording to close a real gap |
| 2026-09-27 | n/a | n/a | Closed the "analyst commentary about named companies" gap |
| 2026-09-29 | n/a | n/a | Closed the Chainlink infra-vs-security gap, trimmed back to flat size |
| 2026-10-02 | n/a | n/a | Added the weekly Slack recap (Mondays 13:05 UTC) so reactions have a visible effect; fixed the 9/25 duplicate; added this log |
| 2026-10-05 | 34 | 9 up / 9 down | Added "a proposal" to the procedural-steps Skip rule -- "Fed/ESMA proposes a rule" and "administration weighs a plan" kept posting as finalized actions (4 down-votes, 9/24-9/30); paid for it by cutting "When in doubt, skip." from the intro |
