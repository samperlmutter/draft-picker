# Draft Advisor

Draft Advisor maintains a local, read-only snapshot of a Sleeper draft. It uses
Sleeper's public API and never asks for or stores a password, token, cookie, or
other private credential.

The checked-in `draft-advisor.json` configures the league, participant, the
five-second draft polling cadence, and the 30-minute cadence reserved for
external value data.

```sh
python3 -m draft_advisor monitor start
python3 -m draft_advisor prepare
python3 -m draft_advisor recommend
python3 -m draft_advisor recommend --json
python3 -m draft_advisor refresh
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

`prepare` starts or verifies the monitor, forces current Sleeper and external
value reads, and leaves a calculated pick plus four backups in the warm cache.
FantasyCalc redraft values are the primary quality signal; Fantasy Football
Calculator ADP is used only to estimate the cost of waiting. Complete external
snapshots and recommendations are atomically activated in the runtime directory.
