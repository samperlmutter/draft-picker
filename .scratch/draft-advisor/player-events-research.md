# Player-event research

Research date: 2026-09-01  
Coverage: current draftable-player snapshot (199 players)  
Packet: `player-events.json`

## Result

The normalized packet is intentionally empty. No current suspension, team
change with a supported production/role risk, or negative role/workload event
was found that met the spec's evidence and severity thresholds. Current player
availability remains sourced from Sleeper and is refreshed separately by the
risk pipeline.

## Review and exclusions

- NFL reported that Puka Nacua *could* face a suspension, but the report did
  not establish a league suspension. This remains unconfirmed and is excluded:
  <https://www.nfl.com/news/puka-nacua-never-considered-contract-holdout-rebuilds-reputation-rams>
- NFL reported that additional discipline for Rashee Rice was unclear. No
  confirmed current suspension was found, so it is excluded:
  <https://www.nfl.com/news/chiefs-andy-reid-expects-rashee-rice-to-be-ready-for-training-camp-after-jail-sentence-knee-surgery>
- DK Metcalf's reported suspension was for the prior season and is expired;
  it does not affect the current-season baseline:
  <https://www.nfl.com/news/steelers-dk-metcalf-relieved-to-be-in-playoffs-declines-to-talk-incident>
- Confirmed offseason transactions such as A.J. Brown's trade are already
  represented in the current player/team and value snapshots. A team change
  alone is not a risk event, and the available official report does not support
  a negative role/workload adjustment:
  <https://www.nfl.com/news/how-does-a-j-brown-fit-into-new-england-s-offense-patriots-just-traded-for-the-missing-piece>

Additional source checks retained from the prior coverage review:

- [NFL: Patriots trade for Eagles WR A.J. Brown](https://www.nfl.com/news/aj-brown-patriots-eagles-trade)
  confirms the team change. The accompanying fit analysis describes an
  expected top-receiver role, which is positive or neutral rather than a risk
  penalty.
- [NFL: Texans WR Nico Collins clarifies his offseason limitation](https://www.nfl.com/news/texans-wr-nico-collins-clarifies-why-he-was-limited-during-offseason-workouts)
  attributes the limitation to planned rest and expected camp readiness. No
  event was added.
- [NFL: 2026 training-camp takeaways](https://www.nfl.com/news/what-we-learned-back-together-weekend-sunday-2026-training-camp)
  describes Jahmyr Gibbs's camp hold-in and a minor reported back issue, but it
  is older than the current Sleeper snapshot and includes editorial
  speculation. No duplicate event was added.
- [NFL: Malik Nabers returns to team drills](https://amp.nfl.com/news/giants-wr-malik-nabers-felt-soul-come-back-to-life-after-participating-in-team-drills)
  documents a gradual return from an ACL injury. This availability dimension
  is already handled by Sleeper, not a separate role/workload penalty.

Missing event data is neutral under the spec. The evaluator still scores all
199 draftable players using the schedule and current Sleeper snapshot.
