# Draft Advisor

Draft Advisor maintains a local, read-only snapshot of a Sleeper draft. It uses
Sleeper's public API and never asks for or stores a password, token, cookie, or
other private credential.

The checked-in `draft-advisor.json` configures the league, participant, the
five-second draft polling cadence, and the 30-minute cadence reserved for
external value data.

```sh
python3 -m draft_advisor monitor start
python3 -m draft_advisor status
python3 -m draft_advisor status --json
python3 -m draft_advisor monitor stop
```

When running from a checkout without installing the package, set
`PYTHONPATH=src`. `DRAFT_ADVISOR_CONFIG` can select another config file and
`DRAFT_ADVISOR_RUNTIME_DIR` can select another local state directory. Tests use
`DRAFT_ADVISOR_FIXTURES` to route all Sleeper reads to recorded JSON responses.

Draft State is replaced atomically. Ordered pick events are appended to
`pick-events.jsonl` in the same compact shape intended for replay.
