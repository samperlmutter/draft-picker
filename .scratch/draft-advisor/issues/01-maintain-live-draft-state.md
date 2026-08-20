# Maintain the live Draft State

Status: ready-for-agent

Estimated scope: 25k–45k tokens

## Parent

[Draft Advisor Specification](../spec.md)

## What to build

Give the Participant one Python CLI that identifies the configured Sleeper league and Participant, reads the current League Rules and draft, and maintains a local Draft State while a five-second monitor runs. The completed slice must be useful on its own: the Participant can start monitoring, inspect current status as text or JSON, see picks and rosters change, and stop monitoring.

The CLI is the product's external interface and the project's test seam. Source access, process management, state updates, and persistence must stay behind that interface.

## Acceptance criteria

- [ ] Project configuration contains the public Sleeper league ID, Participant username, five-second poll interval, and 30-minute external-refresh interval.
- [ ] No Sleeper password, token, session cookie, or other private credential is required or stored.
- [ ] The CLI resolves the Participant's Sleeper user ID and roster from the configured username.
- [ ] The CLI resolves the current draft from the configured league instead of requiring a second configured identifier.
- [ ] Status reports the League Rules, draft type, draft phase, draft order, Participant roster, latest pick, and Participant's next turn when those values are available.
- [ ] Pre-draft status clearly reports an unset start time, unset draft order, incomplete membership, and unset keepers without treating them as errors.
- [ ] Status is available as concise human-readable text and stable JSON.
- [ ] Monitor start creates one local monitor and performs an immediate Sleeper fetch.
- [ ] Starting the monitor again does not create a duplicate process.
- [ ] The active monitor polls the primary draft data every five seconds.
- [ ] Each new pick updates selected-player availability, all affected rosters, current turn, and future turn ownership.
- [ ] Keepers and traded-pick ownership are represented in the Draft State when Sleeper reports them.
- [ ] The monitor writes complete Draft State snapshots atomically so that concurrent readers never observe a partial update.
- [ ] The monitor records ordered pick events in the same event shape that replay can consume later.
- [ ] Status reports the age of the current Draft State.
- [ ] Monitor stop ends the active monitor and reports that it stopped.
- [ ] The monitor stops when Sleeper reports that the draft is complete.
- [ ] CLI failures return a clear message and a nonzero exit status.
- [ ] Tests invoke the CLI as a process with recorded Sleeper responses and isolated runtime state.
- [ ] Tests verify pre-draft inspection, text and JSON output, five-second polling with controlled time, pick updates, keepers, traded picks, duplicate-start prevention, and clean stop behavior.

## Blocked by

- None — can start immediately.
