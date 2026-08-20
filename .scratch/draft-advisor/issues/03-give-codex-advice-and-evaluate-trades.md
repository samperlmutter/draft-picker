# Give Codex advice and evaluate trades

Status: ready-for-agent

Estimated scope: 30k–50k tokens

## Parent

[Draft Advisor Specification](../spec.md)

## What to build

Let the Participant talk to Codex instead of operating the CLI directly. A repository skill teaches Codex to prepare for a turn, return the Calculated Pick and Backup Picks first, add terse Model Judgment, and evaluate a confirmed Trade Offer when asked.

The skill is a thin adapter. All deterministic football logic remains in the CLI. The completed slice supports natural draft language and explicit skill invocation without creating a Codex-only recommendation engine.

## Acceptance criteria

- [ ] Codex discovers a repository skill named `draft-advisor`.
- [ ] The skill can trigger from natural phrases such as "get ready," "who should I pick," and "evaluate this trade."
- [ ] The Participant can invoke the skill explicitly as `$draft-advisor`.
- [ ] "Get ready" calls the CLI preparation behavior and returns a terse readiness result.
- [ ] "Who should I pick?" calls the warm recommendation behavior instead of rebuilding draft logic in the model prompt.
- [ ] Codex reports the Calculated Pick and four Backup Picks before it performs Model Judgment.
- [ ] Codex then gives a terse Final Recommendation that states agreement or a clearly labeled "Updated pick."
- [ ] The later response includes one short roster or scarcity reason, the main risk, and a close alternative when useful.
- [ ] Model Judgment can select only a candidate whose Draft Score is at least 95% of the leading Draft Score.
- [ ] Model Judgment cannot add an unavailable, kept, inactive, or otherwise ineligible Player.
- [ ] Model Judgment does not state unsupported current injuries, NFL teams, depth charts, or news.
- [ ] Current factual claims come from the CLI evidence packet.
- [ ] When time is short, the skill treats the Calculated Pick as actionable and does not require the Participant to wait for Model Judgment.
- [ ] The skill keeps responses terse and does not add a confidence label.
- [ ] The CLI accepts a structured, confirmed Trade Offer containing current-draft picks or Players drafted in the current draft.
- [ ] Codex can parse a natural-language Trade Offer into the structured form required by the CLI.
- [ ] Codex repeats the assets and giving sides and gets Participant confirmation before calling Trade Evaluation.
- [ ] Trade Evaluation runs only after the Participant requests it.
- [ ] Trade Evaluation compares the resulting roster and remaining draft opportunities for the proposed exchange.
- [ ] Trade Evaluation returns `accept`, `reject`, or `close` with one terse reason.
- [ ] Trade Evaluation includes a better counteroffer when one is available.
- [ ] Future-season draft picks are rejected as unsupported.
- [ ] Deterministic recommendation and trade behavior is tested through the CLI seam.
- [ ] A focused Codex acceptance check verifies natural triggering, explicit invocation, preparation, immediate Calculated Pick reporting, bounded Model Judgment, terse output, Trade Offer confirmation, and Trade Evaluation.

## Blocked by

- Keep a Calculated Pick ready.
