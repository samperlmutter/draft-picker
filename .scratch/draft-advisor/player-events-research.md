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

## Sources reviewed and exclusions

- [NFL: Chiefs WR Rashee Rice will not face NFL discipline](https://www.nfl.com/news/chiefs-wr-rashee-rice-will-not-face-nfl-discipline-after-league-investigation)
  reports that the league closed its investigation without discipline. This is
  not a suspension risk.
- [Chiefs: Initial 53-man roster](https://www.chiefs.com/news/here-s-a-look-at-the-chiefs-initial-53-man-roster-x9897)
  lists Rice, Ken Walker, Travis Kelce, Patrick Mahomes, and Xavier Worthy on
  the active roster. No qualifying event was added.
- [NFL: Patriots trade for Eagles WR A.J. Brown](https://www.nfl.com/news/aj-brown-patriots-eagles-trade)
  confirms Brown's team change, while [NFL's fit analysis](https://www.nfl.com/news/how-does-a-j-brown-fit-into-new-england-s-offense-patriots-just-traded-for-the-missing-piece)
  describes an expected top-receiver role. The evidence indicates a positive
  or neutral production change, not a player-event risk penalty.
- [NFL: Texans WR Nico Collins clarifies his offseason limitation](https://www.nfl.com/news/texans-wr-nico-collins-clarifies-why-he-was-limited-during-offseason-workouts)
  attributes the limitation to a planned rest period and says he was expected
  to be ready for camp. No event was added.
- [NFL: 2026 training-camp takeaways](https://www.nfl.com/news/what-we-learned-back-together-weekend-sunday-2026-training-camp)
  describes Jahmyr Gibbs's camp hold-in and a minor reported back issue, but
  the item is older than the current Sleeper snapshot and includes editorial
  speculation. Sleeper remains authoritative for current availability, so no
  duplicate event was added.
- [NFL: Malik Nabers returns to team drills](https://amp.nfl.com/news/giants-wr-malik-nabers-felt-soul-come-back-to-life-after-participating-in-team-drills)
  documents a gradual return from an ACL injury. This is an availability
  dimension already handled by the Sleeper risk snapshot, not a separate role
  or workload penalty.

Missing event data is neutral under the spec. The evaluator will still score
all 199 draftable players using the schedule and current Sleeper snapshot.
