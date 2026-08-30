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
python3 -m draft_advisor trade --offer-file confirmed-trade.json --json
python3 -m draft_advisor replay --input complete-draft.json --json
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

Schedule preparation is an independent cache. By default it downloads the
season schedule and the previous completed season's weekly player stats from
the public nflverse releases, then calculates position-specific opponent
matchup ratings locally. A schedule provider can also be supplied through a
client `schedule(season)` method, recorded fixtures can use
`schedule__<season>.json` (or `schedule.json`) under `DRAFT_ADVISOR_FIXTURES`,
and a configured JSON URL can use `schedule_source_url` in the config (with
`{season}` as an optional placeholder). The provider payload supplies games and
position-specific opponent matchup ratings; the application does not assume
Sleeper exposes either one. Prepared data is stored as `schedule-snapshot.json`
and is reused until its freshness window, League Rules identity, or relevant
player team/position inputs change.
Incomplete or failed refreshes leave the previous valid snapshot intact and
fall back to neutral schedule evidence when no valid snapshot is available.

Risk data uses an explicit validation workflow. Run `draft-advisor risk validate`
to publish a non-authoritative diagnostic snapshot, inspect unresolved items with
`draft-advisor risk review`, record a dated source-linked decision with
`draft-advisor risk override --input override.json`, and then run
`draft-advisor risk refresh` to publish the authoritative snapshot. Invalid,
empty, stale, ambiguous, or weak evidence cannot replace valid risk data; when
no authoritative snapshot is available, recommendations apply no risk penalty.
With no `DRAFT_ADVISOR_FIXTURES` override, validation and refresh read Sleeper's
current `/players/nfl` response and normalize each player's injury designation
or general status. Fixtures remain available for deterministic tests.

The repository skill at `.agents/skills/draft-advisor/SKILL.md` provides the thin
Codex adapter for natural preparation, recommendation, and confirmed-trade
requests. Trade JSON contains `confirmed`, `give`, and `receive`; each asset is a
current-draft `player` with `player_id` or a remaining `pick` with `pick_no`.

`replay` accepts a self-contained initial Draft State, the same ordered pick-event
objects written by the monitor, complete player-value snapshots, refresh points,
an optional prepared `schedule_snapshot`, and confirmed trade checks. It validates
the schedule cache identity against the initial League Rules, performs no source
requests, and returns a concise readiness summary or the first failing
pick/evaluation with diagnostic context. Text Recommendations include compact
regular-season, playoff, and roster-collision evidence; JSON retains the detailed
weekly evidence.
