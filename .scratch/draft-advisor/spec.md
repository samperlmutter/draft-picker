# Draft Advisor Specification

Status: ready-for-agent

## Problem Statement

The Participant is joining a fantasy football draft but does not follow football and has not played fantasy football before. The Participant needs fast, reliable advice that uses the live Sleeper Draft State, current player values, roster needs, and opponent behavior. Sleeper exposes the draft through a free public interface, but that interface is read-only and does not provide enough player-value data to select good Players.

The Participant has less than one minute to act during each turn. A conversational model can add useful judgment, but it can be slow and can contain old or incorrect football facts. The Participant therefore needs an immediate Calculated Pick and Backup Picks before the conversational model gives a terse Final Recommendation.

## Solution

Build a local Python CLI that monitors one Sleeper draft, maintains the latest Draft State, and keeps a Recommendation ready. The CLI is the only external interface to the draft logic. It supplies human-readable output for direct use and structured output for an agent harness.

The CLI combines Sleeper data, FantasyCalc redraft values, and Fantasy Football Calculator ADP. It calculates a Draft Score from player quality, likely availability at the Participant's next pick, roster fit, positional scarcity, injuries, round strategy, and the needs of opponents who select before the Participant's next turn.

Codex receives a repository skill that explains how to use the CLI. When the Participant says "get ready," Codex starts or verifies the monitor, refreshes the Draft State, and prepares a Recommendation. When the Participant asks who to pick, Codex first returns the Calculated Pick and Backup Picks. It then adds terse Model Judgment and returns the Final Recommendation. Model Judgment can change the order only when a candidate's Draft Score is at least 95% of the leading Draft Score.

The Participant always makes the pick in Sleeper. The tool does not submit or prepare Sleeper actions.

## User Stories

1. As the Participant, I want to configure my Sleeper league and username once, so that I do not repeat them during the draft.
2. As the Participant, I want the tool to resolve my Sleeper user ID, so that it can identify my roster without a private credential.
3. As the Participant, I want the tool to resolve the current draft from my league, so that I do not need to copy a separate draft ID.
4. As the Participant, I want the tool to read the League Rules, so that advice matches the real scoring and roster format.
5. As the Participant, I want the tool to detect the draft type, so that it applies snake-draft behavior correctly.
6. As the Participant, I want the tool to detect my draft slot after the commissioner sets the draft order, so that it can find my current and future turns.
7. As the Participant, I want the tool to show when the draft order or start time is not set, so that I know the league is still being configured.
8. As the Participant, I want the tool to work without a Sleeper password or token, so that I do not expose account credentials.
9. As the Participant, I want to start draft monitoring with one command, so that setup is quick on draft day.
10. As the Participant, I want "get ready" to start monitoring when needed, so that I do not have to remember process-management commands.
11. As the Participant, I want "get ready" to verify the monitor when it is already running, so that duplicate monitors are not created.
12. As the Participant, I want the monitor to poll Sleeper every five seconds, so that the Draft State stays current without excessive requests.
13. As the Participant, I want the monitor to detect every new pick, so that selected Players immediately become unavailable.
14. As the Participant, I want the monitor to update every roster after a pick, so that opponent needs remain current.
15. As the Participant, I want the monitor to detect traded draft picks, so that future turn ownership is correct.
16. As the Participant, I want the monitor to detect keepers, so that kept Players are not recommended.
17. As the Participant, I want the monitor to recalculate after each new pick, so that advice is ready before I ask.
18. As the Participant, I want the monitor to stop when the draft completes, so that it does not continue to make requests.
19. As the Participant, I want to request current status, so that I can see the draft phase, latest pick, my roster, and my next turn.
20. As the Participant, I want status to show the age of the Draft State, so that I know how current it is.
21. As the Participant, I want "get ready" to force a current board fetch, so that preparation does not depend only on the poll interval.
22. As the Participant, I want "get ready" to verify my roster and next pick, so that identity or draft-order errors are visible before my turn.
23. As the Participant, I want "get ready" to prepare a Calculated Pick, so that the answer is available immediately when I ask.
24. As the Participant, I want "get ready" to give a short readiness result, so that I know whether I can rely on the next answer.
25. As the Participant, I want to ask "Who should I pick?" in normal language, so that I do not need football or CLI knowledge.
26. As the Participant, I want the Calculated Pick first, so that I can act before Model Judgment is complete.
27. As the Participant, I want ordered Backup Picks with the Calculated Pick, so that I have alternatives if another team selects the first Player.
28. As the Participant, I want the calculated result to be available from the warm cache in less than one second, so that the tool does not consume my turn.
29. As the Participant, I want the full agent response to target 15 seconds, so that I still have time to select the Player in Sleeper.
30. As the Participant, I want the immediate answer to remain useful without Model Judgment, so that a slow model does not block my pick.
31. As the Participant, I want advice to use full-PPR player values, so that it matches my league's reception scoring.
32. As the Participant, I want advice to account for my open starting positions, so that I build a usable roster.
33. As the Participant, I want advice to account for FLEX positions, so that RB, WR, and eligible TE Players receive correct roster value.
34. As the Participant, I want advice to use soft position limits, so that unusual value can override a normal roster pattern.
35. As the Participant, I want the tool to usually select one QB and one TE before considering backups, so that scarce bench space is used well.
36. As the Participant, I want the tool to avoid a bench K or DEF, so that those low-value positions do not consume extra roster slots.
37. As the Participant, I want K and DEF selections to occur in the final rounds, so that early picks go to more valuable positions.
38. As the Participant, I want most bench slots to contain RB and WR Players, so that the bench supports FLEX needs and upside.
39. As the Participant, I want dependable starters favored in early rounds, so that the roster has a stable base.
40. As the Participant, I want higher-upside Players favored in later rounds, so that bench picks can exceed their expected value.
41. As the Participant, I want inactive Players removed from consideration, so that the tool does not recommend a Player who cannot contribute.
42. As the Participant, I want Players marked Out, IR, or PUP to receive a strong penalty, so that the lack of an injured-reserve roster slot is respected.
43. As the Participant, I want an explicit warning when an injured Player still ranks highly, so that I understand the risk.
44. As the Participant, I want ADP used as a timing signal, so that the tool can estimate whether a Player can wait until my next turn.
45. As the Participant, I do not want ADP treated as proof of player quality, so that market behavior does not replace the player-value signal.
46. As the Participant, I want positional scarcity included, so that the tool measures the cost of waiting at each position.
47. As the Participant, I want the tool to model the needs of teams that pick before my next turn, so that its availability estimate reflects the live board.
48. As the Participant, I do not want weak blocking picks, so that opponent modeling does not damage my roster.
49. As the Participant, I want shared bye weeks used only as a tie-breaker, so that a clearly better Player is not rejected.
50. As the Participant, I want Players from the same NFL team treated only as a tie-breaker, so that team combinations do not dominate player value.
51. As the Participant, I want each Draft Score to be deterministic from the same input, so that advice can be tested and replayed.
52. As the Participant, I want the Draft Score to remain a relative comparison, so that it is not presented as an exact win probability.
53. As the Participant, I want to see the main evidence behind the Calculated Pick, so that I can understand the result without knowing football.
54. As the Participant, I want FantasyCalc values refreshed during a long draft, so that the baseline can reflect current market information.
55. As the Participant, I want ADP refreshed during a long draft, so that the timing signal can reflect current draft behavior.
56. As the Participant, I want external values refreshed every 30 minutes, so that slow-moving sources do not receive the five-second polling load.
57. As the Participant, I want each external refresh applied as one complete snapshot, so that a partial refresh cannot mix old and new rankings.
58. As the Participant, I want Sleeper player identifiers used where available, so that Players are matched correctly across sources.
59. As the Participant, I want uncertain player matches rejected instead of guessed, so that one Player's value is not assigned to another Player.
60. As the Participant, I want the conversational model to receive only the relevant candidates and evidence, so that Model Judgment is fast and grounded.
61. As the Participant, I want Model Judgment to be supplemental, so that calculated evidence remains the main selection method.
62. As the Participant, I want Model Judgment limited to candidates within 5% of the leading Draft Score, so that it cannot override a clear result.
63. As the Participant, I want the model to say whether it agrees with the Calculated Pick, so that its position is clear.
64. As the Participant, I want the model to give one short roster or scarcity reason, so that the later response stays terse.
65. As the Participant, I want the model to identify the main risk, so that I know the most important reason the pick could fail.
66. As the Participant, I want the model to identify a close Backup Pick when one exists, so that I can make a quick alternate choice.
67. As the Participant, I want a changed pick labeled "Updated pick," so that the model never changes advice silently.
68. As the Participant, I do not want the model to state unsupported current injuries, teams, depth charts, or news, so that remembered facts are not presented as current data.
69. As the Participant, I want to use the Calculated Pick immediately when time is short, so that Model Judgment cannot cause a missed pick.
70. As the Participant, I do not want a confidence label, so that the response remains short.
71. As the Participant, I want to describe a Trade Offer in normal language, so that I do not need a special trade syntax.
72. As the Participant, I want the Draft Assistant to repeat its interpretation of a Trade Offer, so that I can correct wrong assets or giving sides.
73. As the Participant, I want to confirm a Trade Offer before evaluation, so that advice uses the intended exchange.
74. As the Participant, I want Trade Evaluation only when I request it, so that normal draft advice remains focused.
75. As the Participant, I want Trade Evaluation to support current-draft picks, so that I can assess a pick swap during the draft.
76. As the Participant, I want Trade Evaluation to support Players already drafted, so that I can assess mixed Player and pick offers.
77. As the Participant, I want Trade Evaluation to return accept, reject, or close, so that the result is quick to understand.
78. As the Participant, I want Trade Evaluation to include one short reason, so that the decision is explained without delaying the draft.
79. As the Participant, I want a better counteroffer when one exists, so that I can act on a rejected or close Trade Offer.
80. As the Participant, I want trades evaluated against my resulting roster and remaining picks, so that asset values are not considered in isolation.
81. As the Participant, I want the CLI to return readable text, so that I can use it directly if needed.
82. As the Participant, I want the CLI to return structured JSON, so that Codex and other harnesses can consume the same result.
83. As the Participant, I want CLI errors to use clear messages and nonzero exit codes, so that an agent can detect a failed operation.
84. As the Participant, I want the agent skill to trigger from "get ready," so that draft preparation feels conversational.
85. As the Participant, I want the agent skill to trigger from "who should I pick," so that recommendation requests feel conversational.
86. As the Participant, I want the agent skill to trigger from "evaluate this trade," so that trade advice feels conversational.
87. As the Participant, I want to invoke the skill explicitly when automatic discovery fails, so that I have a reliable fallback.
88. As the Participant, I want the skill to keep football logic in the CLI, so that another harness can use the same behavior.
89. As the Participant, I want one full draft replay before the real draft, so that timing and state transitions are verified.
90. As the Participant, I want replay to use the same recommendation interface as live mode, so that the test exercises production behavior.
91. As the Participant, I want replay to cover every one of my turns, so that all 15 roster decisions are checked.
92. As the Participant, I want replay to cover keepers, so that a kept Player cannot appear as available.
93. As the Participant, I want replay to cover traded picks, so that turn ownership remains correct.
94. As the Participant, I want replay to cover position runs, so that opponent-based availability changes are verified.
95. As the Participant, I want replay to cover injury penalties, so that risky Players are handled as designed.
96. As the Participant, I want replay to cover the final K and DEF selections, so that the completed roster follows League Rules.
97. As the Participant, I want replay to cover Trade Evaluation, so that current-pick and Player exchanges are verified.
98. As the Participant, I want replay results to be repeatable, so that a changed result indicates a real logic or data change.

## Implementation Decisions

- The product is a personal Draft Assistant for one Sleeper league and one 2026 draft. It is not a multi-user or commercial product.
- Python 3 is the implementation language. Runtime dependencies must remain small. Standard-library capabilities are preferred when they provide a clear implementation.
- The CLI module is the sole external interface and the highest test seam. All monitoring, source access, player matching, Draft Score calculation, roster strategy, replay, and Trade Evaluation behavior stays behind this interface.
- The CLI interface supports monitor start, monitor stop, status, prepare, recommend, trade evaluation, replay, and player-event risk evaluation operations.
- Every operation supports a human-readable result. Read operations and evaluations also support a stable JSON result for agent harnesses.
- Project configuration stores the Sleeper league ID, Participant username, five-second poll interval, and 30-minute external-source refresh interval. It stores no Sleeper credentials.
- Runtime state is local and is not versioned. The monitor writes complete Draft State snapshots atomically so that a concurrent recommendation never reads a partial update.
- The monitor records a compact ordered pick-event history. Replay reads the same event shape that live monitoring produces.
- Sleeper is the source of League Rules, draft metadata, users, rosters, picks, traded picks, keepers, player identifiers, and current injury designations.
- The Sleeper polling interval is five seconds while draft mode is active. A prepare operation performs an immediate fetch without changing the normal interval.
- FantasyCalc supplies the primary redraft player-value signal for a 12-team, one-QB, full-PPR format.
- Fantasy Football Calculator supplies 12-team, full-PPR ADP. ADP is a timing and expected-availability signal, not the primary player-quality signal.
- External player values refresh at monitor startup and every 30 minutes during draft mode. A manual refresh operation is also available.
- An external refresh becomes active only after the complete payload is validated and matched. Partial data never replaces the current value snapshot.
- Cross-source matching uses Sleeper player identifiers when a source supplies them. A normalized name, NFL team, and position composite can be used only when an identifier is unavailable. Ambiguous matches are omitted and reported.
- The recommendation module recalculates after every new pick and after every accepted external value snapshot.
- Draft Score is deterministic for the same Draft State and value snapshot. It is a relative comparison and is never described as a win probability.
- Draft Score combines primary player value, roster fit, positional scarcity, expected availability at the Participant's next turn, opponent roster needs, injury status, and round-dependent risk preference.
- ADP changes the cost of waiting. It cannot make a materially weaker Player the leader only because that Player is commonly drafted early.
- Opponent modeling considers only teams scheduled to pick before the Participant's next turn. It estimates likely position demand and player survival; it does not reward blocking another team by making a weak pick.
- The roster strategy uses soft position limits. It usually selects one QB and one TE before backups, fills RB, WR, and FLEX capacity, keeps most bench positions for RB and WR, never selects a bench K or DEF, and delays K and DEF until the final rounds.
- Early rounds favor dependable starting value. Later rounds increase the value of upside. Shared bye weeks and Players from one NFL team are tie-breakers only.
- Inactive Players are not eligible. Out, IR, and PUP designations receive a strong penalty. If such a Player remains competitive, the output includes an injury warning.
- The player-event and schedule-risk evaluation covers every draftable Player for the current fantasy season, including regular-season and playoff weeks. Regular-season impact receives more weight because it affects more fantasy weeks.
- Schedule risk uses opponent strength by position, bye weeks, and playoff matchup quality. It excludes travel, weather, and speculative narratives.
- Player events are limited to current injury or availability, suspension, team change, and meaningful role or workload change. A team change alone is not a risk event; it matters only when credible evidence indicates a production or role change.
- Sleeper is authoritative for current availability. Official team or NFL information is authoritative for role and suspension events. Structured historical data establishes schedule context. Contradictory sources are resolved independently by dimension, with the most recent authoritative source winning; reports are never averaged.
- A research event uses the normalized fields `player_id`, `event_type`, `impact_tier`, `summary`, `observed_at`, optional `effective_at`, optional `expires_at`, `source`, and `evidence_url`. `event_type` is one of `availability`, `suspension`, `team_change`, `role_change`, or `workload_change`; `impact_tier` is `none`, `material`, or `severe`.
- A material event plausibly affects one or more games or meaningfully changes expected usage. A severe event plausibly causes a multi-week absence, suspension, or major loss of role. Events without credible evidence have no score effect.
- The evaluation produces one schedule tier, one player-event tier, a bounded combined Draft Score adjustment, and the evidence supporting each result. Schedule matchup quality may produce a bounded positive adjustment. Player events may only reduce or leave a score unchanged.
- The combined schedule and event adjustment is capped at 10% of the pre-risk Draft Score. The default tier adjustments are 0% for no material impact, -3% for material risk, and -8% to -10% for severe risk. Existing hard availability rules for inactive or Out/IR/PUP Players remain in force.
- Multiple events for one Player use the latest authoritative event in each category. Duplicate events do not stack; only the highest applicable severity is applied.
- The pre-draft evaluation establishes a baseline snapshot for all draftable Players. The day-of evaluation runs the same logic immediately before preparation, scores from its current snapshot, and reports only material changes with the old tier, new tier, reason, and source. Severe changes are always reported.
- Missing event data is neutral. If the day-of evaluation cannot complete, the last valid baseline remains usable but is marked stale or incomplete; no new penalty is introduced without fresh evidence.
- The CLI exposes `risk evaluate --phase baseline` and `risk evaluate --phase day-of`. Both consume the same current schedule, value, availability, and research-event inputs; day-of additionally compares against the stored baseline. The resulting evaluation is attached to the authoritative risk snapshot so live Recommendations, replay, and the evidence packet use the same data.
- The immediate recommendation result contains one Calculated Pick and four ordered Backup Picks with compact component evidence.
- A candidate is eligible for a model-driven reorder only when its Draft Score is at least 95% of the leading Draft Score.
- The CLI produces a compact evidence packet for the agent. It includes only the leading candidates, Draft Score components, roster fit, injury flags, scarcity, expected survival, and relevant opponent needs.
- The CLI never calls an LLM. Model Judgment belongs to the harness adapter so that the core remains harness-independent.
- The Codex adapter is a repository skill. Codex can discover it from normal draft language or the Participant can invoke it explicitly as `$draft-advisor`.
- Codex first reports the Calculated Pick and Backup Picks. It then gives terse Model Judgment that states agreement or a clearly labeled Updated pick, one reason, the main risk, and a close alternative when useful.
- Model Judgment cannot introduce unsupported claims about current injuries, teams, depth charts, or news. Current factual claims must come from the CLI evidence packet.
- If Model Judgment is not available quickly enough, the Calculated Pick remains actionable. The Participant never waits for Model Judgment when less than 15 seconds remain.
- The prepare operation starts the monitor when it is absent, avoids duplicate monitors, performs a current fetch, validates the Participant roster and next turn, calculates a current result, and returns a short readiness report.
- The Draft Assistant never submits a Sleeper pick. Sleeper interaction is read-only, and the Participant selects every Player manually.
- Natural-language Trade Offer parsing belongs to the agent adapter. The agent restates the assets and giving sides and obtains confirmation before it calls the structured trade-evaluation operation.
- Trade Evaluation supports current-draft picks and Players drafted in the current draft. It does not value future-season picks.
- Trade Evaluation compares the expected roster and remaining draft opportunities on both sides. It returns accept, reject, or close, one terse reason, and a better counteroffer when one is available.
- The current League Rules are a 12-team, 15-round snake draft with full-PPR scoring, one QB, two RB, two WR, one TE, two FLEX, one K, one DEF, and five bench positions. The Sleeper data remains authoritative if the commissioner changes these settings.
- The current league permits one keeper and pick trading. Keepers are currently unset. The implementation detects live keeper and traded-pick data instead of assuming the current pre-draft state will remain unchanged.
- The current Participant owns roster 8. Draft slot, draft start time, and final membership are not yet set, so they must be resolved from Sleeper at runtime.

## Testing Decisions

- The CLI interface is the single test seam. Tests exercise the product as a caller does instead of testing internal implementation details.
- A good test supplies recorded source responses and pick events, invokes a CLI operation as a process, and asserts visible text, JSON, exit status, persisted Draft State, or elapsed time.
- Tests use isolated temporary runtime state. They do not call live Sleeper, FantasyCalc, or Fantasy Football Calculator endpoints.
- Recorded responses represent the real external payload shapes. Internal adapters are tested through the CLI behavior that depends on those payloads.
- The monitor-start test verifies one monitor starts and a repeated start does not create a duplicate.
- The prepare test verifies an absent monitor starts, current data is loaded, the Participant and next turn are resolved, and a Recommendation becomes available.
- Pre-draft tests cover an unset start time, unset draft order, incomplete league membership, and unset keepers.
- Live-monitor tests feed ordered pick events and verify that Players become unavailable, rosters update, and recommendations recalculate.
- Polling tests use controlled time and recorded responses to verify the five-second Sleeper cadence without making the suite wait in real time.
- External-refresh tests use controlled time to verify the 30-minute cadence and atomic activation of a validated snapshot.
- Player-matching tests verify native Sleeper identifiers, safe composite matching, and rejection of ambiguous matches through visible CLI results.
- Recommendation tests verify that the same Draft State and value snapshot always produce the same Draft Score order.
- Strategy tests verify roster fit, FLEX eligibility, soft QB and TE limits, RB and WR bench preference, final-round K and DEF behavior, early-round stability, and late-round upside.
- Availability tests verify that ADP and the needs of intervening opponents change wait cost without replacing primary player value.
- Injury tests verify inactive exclusion, Out/IR/PUP penalties, and visible warnings for competitive injured Players.
- Player-event evaluation tests run the CLI baseline and day-of phases with recorded schedule, availability, and official-event packets. They verify tier classification, bounded score adjustments, source precedence, duplicate suppression, stale/expired events, baseline diffs, and fallback to the last valid baseline.
- Keeper tests verify that kept Players never appear as available candidates.
- Traded-pick tests verify that the current and future Participant turns follow live ownership instead of the original draft slot.
- Output tests verify one Calculated Pick, four ordered Backup Picks, compact evidence, human-readable text, stable JSON, and no confidence label.
- Model-eligibility tests verify that only candidates at or above 95% of the leading Draft Score are marked as eligible for a model-driven reorder.
- Warm-cache performance tests verify that the calculated recommendation command completes in less than one second on the target laptop.
- Trade tests invoke the structured, confirmed trade operation and verify accept, reject, close, terse reasons, current-draft asset support, Player support, and useful counteroffers.
- Trade tests verify that future-season picks are rejected as unsupported.
- Replay tests send a complete recorded or synthetic 12-team, 15-round draft through the CLI. They verify all Participant turns, legal final roster construction, keepers, traded picks, position runs, injury penalties, and repeatable output.
- Codex skill behavior is checked at the CLI seam for all deterministic work. The skill itself receives a focused manual acceptance check for natural triggering, explicit `$draft-advisor` triggering, immediate Calculated Pick reporting, terse Model Judgment, and confirmed Trade Offer parsing.
- There is no prior test pattern in the repository because the repository is new. The CLI seam established by this specification becomes the project test pattern.

## Out of Scope

- Submitting, queuing, or preparing picks in Sleeper.
- Browser automation or private Sleeper interfaces.
- A web application, browser extension, or visual draft board.
- Hosted monitoring or a multi-user service.
- Desktop, sound, chat, or mobile turn notifications.
- Infrastructure high availability, automatic failover, or source redundancy.
- Manual CSV backup workflows.
- Exact championship probability or full-season simulation.
- Commercial use or redistribution of source data.
- Future-season draft-pick valuation.
- Automatic trade detection or unsolicited Trade Evaluation.
- Waiver, lineup, matchup, or in-season management.
- Current-news web searches during each pick.
- Confidence labels.
- Harness-specific adapters other than Codex in the first version.

## Further Notes

- The Sleeper public interface is read-only and free for noncommercial use. It advises callers to remain below 1,000 requests per minute. A five-second live poll produces 12 requests per minute for the primary draft endpoint.
- The configured league ID is `1396148699033264128`.
- The configured Participant username is `sperlmutter`, with Sleeper user ID `1396260914679795712`.
- The current Sleeper draft ID is `1396148700635484160`.
- The current Sleeper pick timer is 120 seconds, but the product is designed for the Participant's stricter goal of acting in less than one minute.
- FantasyCalc has a public interface and native Sleeper player identifiers, but it is not treated as a supported service contract.
- Fantasy Football Calculator states that its ADP data can be used through its free interface. The current 12-team PPR sample is based on recent human mock drafts.
- The commissioner has not set the draft start time or draft order. The Participant will provide the date when it is known, and the runtime will read the final order directly from Sleeper.
- The Participant is responsible for keeping the laptop awake during draft mode.
- The Participant has asked the tool to own football strategy decisions. The implementation must follow the strategy rules in this specification without asking the Participant to make position or football-knowledge choices.
