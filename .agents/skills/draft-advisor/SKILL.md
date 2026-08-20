---
name: draft-advisor
description: Prepare for a Sleeper draft turn, answer “who should I pick?”, or parse and confirm a requested Trade Offer before evaluation. Use for natural phrases including “get ready,” “who should I pick,” and “evaluate this trade,” or when explicitly invoked as $draft-advisor.
---

# Draft Advisor

Use the repository CLI as the only source of deterministic football logic. Never
submit, queue, or prepare a Sleeper pick.

## Get ready

Run `python3 -m draft_advisor prepare --json`. Report only whether monitoring is
ready, the verified roster, the next turn, and the Calculated Pick. Do not rebuild
the recommendation yourself.

## Who should I pick?

Run `python3 -m draft_advisor recommend --json` and immediately report the
Calculated Pick followed by all four ordered Backup Picks. This result is
actionable without waiting for later judgment.

Then provide a terse `Final Recommendation:`. State either `Agree:` with the
Calculated Pick or `Updated pick:`. An updated pick must be one of the returned
candidates whose `model_judgment_eligible` field is true. Never introduce another
Player or alter the order because of remembered football facts.

Give one short roster-fit or scarcity reason from the candidate evidence, the
main risk present in that evidence, and a close eligible alternative when useful.
Current injuries, teams, availability, and opponent needs may be stated only
when present in the CLI JSON. Do not search for or invent current news, depth
charts, or injury facts. Keep the response terse and never add confidence labels.

If the Participant says time is short, return the Calculated Pick and backups and
stop; Model Judgment is optional.

## Evaluate a trade

Only evaluate when the Participant asks. Parse their natural language into:

```json
{
  "confirmed": false,
  "give": [{"type": "player", "player_id": "..."}],
  "receive": [{"type": "pick", "pick_no": 12}]
}
```

Assets are Players already drafted in this draft or numbered picks remaining in
this draft. Use `python3 -m draft_advisor status --json` only when needed to
resolve the recorded Player IDs, pick numbers, and ownership. Reject future-season
picks without evaluating them. Restate both sides in plain language and ask the
Participant to confirm.
Do not run Trade Evaluation before an explicit confirmation.

After confirmation, set `confirmed` to true, write the exact JSON to a temporary
file, and run `python3 -m draft_advisor trade --offer-file <path> --json`. Relay
the CLI's accept/reject/close decision, one reason, and counteroffer when present.
Do not add a separate football valuation.
