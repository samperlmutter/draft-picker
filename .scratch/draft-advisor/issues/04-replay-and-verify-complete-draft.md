# Replay and verify a complete draft

Status: ready-for-agent

Estimated scope: 20k–40k tokens

## Parent

[Draft Advisor Specification](../spec.md)

## What to build

Prove that the Draft Assistant is ready for the real draft by replaying one complete 12-team, 15-round draft through the same CLI interface and event shape used in live mode. The replay must make every Participant turn visible, produce legal and repeatable Recommendations, exercise Trade Evaluation, and finish with a valid roster.

The completed slice is both a user-visible replay command and the final end-to-end acceptance suite. It must not create a second recommendation path used only by tests.

## Acceptance criteria

- [ ] The CLI can replay a complete recorded or synthetic 12-team, 15-round snake draft.
- [ ] Replay consumes the same ordered pick-event shape recorded by the live monitor.
- [ ] Replay uses the same Draft State, Draft Score, Recommendation, and Trade Evaluation behavior as live mode.
- [ ] Replay does not make live network requests.
- [ ] Replay covers all 180 draft picks and all 15 Participant turns.
- [ ] Every Participant turn produces one Calculated Pick and four ordered Backup Picks from Players available at that moment.
- [ ] The replayed Participant roster remains legal after every pick and at draft completion.
- [ ] The final roster contains the required QB, RB, WR, TE, FLEX, K, DEF, and bench capacity.
- [ ] K and DEF occur in the final rounds and no bench K or DEF is selected.
- [ ] Most bench selections are RB or WR unless the data shows unusual value at QB or TE.
- [ ] Replay covers at least one keeper and verifies that the kept Player is never recommended.
- [ ] Replay covers at least one traded pick and verifies that turn ownership changes correctly.
- [ ] Replay covers an opponent position run and verifies that expected player survival changes.
- [ ] Replay covers an injured high-value Player and verifies the penalty and warning.
- [ ] Replay covers an ambiguous cross-source player match and verifies that the match is rejected.
- [ ] Replay covers an external value refresh and verifies that a complete validated snapshot replaces the prior snapshot.
- [ ] Replay covers a model-eligible close candidate and a candidate outside the 5% Model Judgment limit.
- [ ] Replay covers accepted, rejected, and close Trade Evaluations.
- [ ] Replay covers a useful counteroffer.
- [ ] Replay rejects a Trade Offer that contains a future-season pick.
- [ ] Repeating replay with the same inputs produces the same deterministic Calculated Picks and Trade Evaluations.
- [ ] Replay reports a concise pass or failure summary as text and structured JSON.
- [ ] A failed replay identifies the first failing pick or evaluation with enough visible context to diagnose the behavior.
- [ ] The full suite exercises the CLI as a process and does not test private implementation details.
- [ ] The real-draft readiness check includes one successful complete replay before draft day.

## Blocked by

- Give Codex advice and evaluate trades.
