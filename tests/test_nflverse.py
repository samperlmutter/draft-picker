from __future__ import annotations

import unittest

from src.draft_advisor.nflverse import NflverseScheduleProvider


SCHEDULE = """game_id,season,game_type,week,away_team,home_team
2026_01_AAA_BBB,2026,REG,1,AAA,BBB
2026_02_CCC_AAA,2026,REG,2,CCC,AAA
2026_19_AAA_BBB,2026,POST,19,AAA,BBB
"""

STATS = """season,season_type,game_id,team,opponent_team,position,fantasy_points_ppr
2025,REG,g1,AAA,BBB,QB,30
2025,REG,g1,AAA,BBB,RB,10
2025,REG,g1,AAA,BBB,WR,20
2025,REG,g1,AAA,BBB,TE,8
2025,REG,g2,BBB,AAA,QB,10
2025,REG,g2,BBB,AAA,RB,5
2025,REG,g2,BBB,AAA,WR,10
2025,REG,g2,BBB,AAA,TE,4
2025,REG,g3,CCC,AAA,QB,20
2025,REG,g3,CCC,AAA,RB,8
2025,REG,g3,CCC,AAA,WR,16
2025,REG,g3,CCC,AAA,TE,6
2025,REG,g4,AAA,CCC,QB,30
2025,REG,g4,AAA,CCC,RB,10
2025,REG,g4,AAA,CCC,WR,20
2025,REG,g4,AAA,CCC,TE,8
"""


class NflverseTests(unittest.TestCase):
    def test_provider_normalizes_schedule_and_derives_ratings(self) -> None:
        payloads = {
            "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv": SCHEDULE,
            "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_2025.csv": STATS,
        }
        provider = NflverseScheduleProvider(fetch_text=payloads.__getitem__)
        payload = provider.schedule(2026)

        self.assertEqual(payload["season"], 2026)
        self.assertEqual(len(payload["games"]), 2)
        self.assertEqual(payload["games"][0]["away_team"], "AAA")
        self.assertIn("QB", payload["opponent_ratings"]["BBB"]["defense"])
        self.assertIn("DEF", payload["opponent_ratings"]["AAA"]["offense"])
        self.assertIn("ALL", payload["opponent_ratings"]["BBB"]["defense"])
        self.assertGreater(payload["opponent_ratings"]["BBB"]["defense"]["QB"], 0)
        self.assertGreater(payload["opponent_ratings"]["BBB"]["offense"]["DEF"], 0)


if __name__ == "__main__":
    unittest.main()
