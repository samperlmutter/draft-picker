# Keep a Calculated Pick ready

Status: ready-for-agent

Estimated scope: 50k–80k tokens

## Parent

[Draft Advisor Specification](../spec.md)

## What to build

Turn the maintained Draft State into an immediate, data-based Recommendation. The Participant can prepare for a turn and receive one Calculated Pick plus four ordered Backup Picks. The result uses current player value, expected availability, roster fit, positional scarcity, injuries, round strategy, opponent needs, keepers, and traded picks.

The completed slice must keep a Recommendation warm after every new pick and return it through the CLI in less than one second. It must own football strategy without asking the Participant to choose positions or tactics.

## Acceptance criteria

- [ ] FantasyCalc supplies the primary redraft player-value signal for a 12-team, one-QB, full-PPR format.
- [ ] Fantasy Football Calculator supplies 12-team, full-PPR ADP as a timing and expected-availability signal.
- [ ] Sleeper supplies League Rules, rosters, picks, keepers, traded picks, player identifiers, and injury designations.
- [ ] External player-value data refreshes at monitor startup, every 30 minutes during draft mode, and after an explicit refresh request.
- [ ] A new external snapshot becomes active only after the complete response is validated and matched.
- [ ] Player matching uses Sleeper identifiers when available and a normalized name, NFL team, and position composite only when required.
- [ ] Ambiguous player matches are omitted and reported instead of guessed.
- [ ] Draft Score is deterministic for the same Draft State and external value snapshot.
- [ ] Draft Score is presented as a relative player comparison and never as win probability.
- [ ] Primary player value remains the main quality signal.
- [ ] ADP changes the cost of waiting and cannot make a materially weaker Player the leader only because the Player is drafted early by the market.
- [ ] Roster fit accounts for all configured starting positions and FLEX eligibility.
- [ ] Positional scarcity measures the cost of waiting until the Participant's next turn.
- [ ] Opponent modeling considers the roster needs of teams that select before the Participant's next turn.
- [ ] Opponent modeling estimates player survival and does not reward a weak blocking pick.
- [ ] The strategy uses soft position limits and normally selects one QB and one TE before adding backups.
- [ ] Most bench value is assigned to RB and WR Players.
- [ ] The strategy never selects a bench K or DEF.
- [ ] K and DEF are delayed until the final rounds.
- [ ] Early rounds favor dependable starting value and later rounds increase the value of upside.
- [ ] Shared bye weeks and Players from the same NFL team are tie-breakers only.
- [ ] Inactive Players are not eligible for a Recommendation.
- [ ] Out, IR, and PUP designations receive a strong penalty.
- [ ] A competitive injured Player receives a visible warning.
- [ ] Kept and selected Players never appear in the available candidate set.
- [ ] Traded-pick ownership changes the Participant's current and future turn calculations.
- [ ] A Recommendation contains one Calculated Pick and four ordered Backup Picks.
- [ ] Each candidate includes compact evidence for Draft Score components, roster fit, injury status, scarcity, expected survival, and relevant opponent needs.
- [ ] Candidates with a Draft Score at least 95% of the leading Draft Score are marked as eligible for Model Judgment.
- [ ] The prepare operation starts the monitor when absent, avoids duplicates, forces a current fetch, verifies the Participant roster and next turn, prepares a Recommendation, and returns a terse readiness result.
- [ ] The recommendation recalculates after every new pick and every accepted external value snapshot.
- [ ] A warm recommendation returns through the CLI in less than one second on the target laptop.
- [ ] Recommendation output is available as concise human-readable text and stable JSON.
- [ ] Recommendation output does not contain a confidence label.
- [ ] Tests exercise all behavior through the CLI with recorded source responses, controlled time, and isolated runtime state.
- [ ] Tests verify deterministic ordering, data matching, atomic refreshes, roster strategy, injuries, keepers, traded picks, opponent demand, position runs, text and JSON output, Model Judgment eligibility, preparation, and warm-cache performance.

## Blocked by

- Maintain the live Draft State.
