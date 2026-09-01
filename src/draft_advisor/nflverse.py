from __future__ import annotations

import csv
import io
import math
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from typing import Any, Callable


SCHEDULE_URL = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"
STATS_URL = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{season}.csv"
OFFENSIVE_POSITIONS = ("QB", "RB", "WR", "TE")


class NflverseUnavailable(ValueError):
    """nflverse data could not be downloaded."""


def _number(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def _download(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "draft-advisor/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, UnicodeDecodeError) as exc:
        raise NflverseUnavailable(f"nflverse request failed: {url}: {exc}") from exc


def _rows(content: str, label: str) -> list[dict[str, str]]:
    try:
        rows = list(csv.DictReader(io.StringIO(content)))
    except csv.Error as exc:
        raise ValueError(f"nflverse {label} CSV is invalid: {exc}") from exc
    if not rows:
        raise ValueError(f"nflverse {label} CSV is empty")
    return rows


def _schedule_games(content: str, season: int) -> list[dict[str, Any]]:
    games: list[dict[str, Any]] = []
    for row in _rows(content, "schedule"):
        if str(row.get("season") or "") != str(season) or row.get("game_type") != "REG":
            continue
        try:
            week = int(row["week"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("nflverse schedule has an invalid regular-season week") from exc
        away, home = str(row.get("away_team") or "").strip().upper(), str(row.get("home_team") or "").strip().upper()
        if not away or not home or away == home or not 1 <= week <= 18:
            raise ValueError("nflverse schedule has an invalid regular-season game")
        games.append({
            "game_id": str(row.get("game_id") or f"{season}_{week}_{away}_{home}"),
            "week": week,
            "home_team": home,
            "away_team": away,
        })
    if not games:
        raise ValueError(f"nflverse schedule has no regular-season games for {season}")
    return games


def _opponent_ratings(content: str, rating_season: int) -> dict[str, dict[str, dict[str, float]]]:
    rows = _rows(content, "weekly player stats")
    defensive_points: dict[tuple[str, str], float] = defaultdict(float)
    defensive_games: dict[tuple[str, str], set[str]] = defaultdict(set)
    all_defensive_points: dict[str, float] = defaultdict(float)
    all_defensive_games: dict[str, set[str]] = defaultdict(set)
    offensive_points: dict[str, float] = defaultdict(float)
    offensive_games: dict[str, set[str]] = defaultdict(set)
    teams: set[str] = set()
    for row in rows:
        if str(row.get("season") or "") != str(rating_season) or row.get("season_type") != "REG":
            continue
        team = str(row.get("team") or "").strip().upper()
        opponent = str(row.get("opponent_team") or "").strip().upper()
        game_id = str(row.get("game_id") or "")
        position = str(row.get("position") or "").strip().upper()
        if not team or not opponent or not game_id:
            continue
        teams.update((team, opponent))
        if position not in OFFENSIVE_POSITIONS:
            continue
        points = _number(row.get("fantasy_points_ppr"))
        defensive_points[(opponent, position)] += points
        defensive_games[(opponent, position)].add(game_id)
        all_defensive_points[opponent] += points
        all_defensive_games[opponent].add(game_id)
        offensive_points[team] += points
        offensive_games[team].add(game_id)

    position_league_totals: Counter[str] = Counter()
    position_league_games: Counter[str] = Counter()
    for (team, position), points in defensive_points.items():
        position_league_totals[position] += points
        position_league_games[position] += len(defensive_games[(team, position)])
    position_league_average = {
        position: position_league_totals[position] / position_league_games[position]
        for position in OFFENSIVE_POSITIONS
        if position_league_games[position]
    }
    all_defense_games = sum(len(games) for games in all_defensive_games.values())
    all_defense_average = sum(all_defensive_points.values()) / all_defense_games if all_defense_games else 0.0
    offense_league_total = sum(offensive_points.values())
    offense_league_games = sum(len(games) for games in offensive_games.values())
    offense_league_average = offense_league_total / offense_league_games if offense_league_games else 0.0
    if not teams or not position_league_average or not all_defense_average or not offense_league_average:
        raise ValueError(f"nflverse stats have insufficient regular-season data for {rating_season}")

    ratings: dict[str, dict[str, dict[str, float]]] = {}
    for team in sorted(teams):
        defense: dict[str, float] = {}
        for position in OFFENSIVE_POSITIONS:
            games = len(defensive_games[(team, position)])
            if not games:
                continue
            average_allowed = defensive_points[(team, position)] / games
            baseline = max(1.0, position_league_average[position])
            defense[position] = round(max(-1.0, min(1.0, (average_allowed - position_league_average[position]) / baseline)), 6)
        games = len(all_defensive_games[team])
        if games:
            average_allowed = all_defensive_points[team] / games
            baseline = max(1.0, all_defense_average)
            defense["ALL"] = round(max(-1.0, min(1.0, (average_allowed - all_defense_average) / baseline)), 6)
        games = len(offensive_games[team])
        offense: dict[str, float] = {}
        if games:
            average_points = offensive_points[team] / games
            baseline = max(1.0, offense_league_average)
            offense["DEF"] = round(max(-1.0, min(1.0, (offense_league_average - average_points) / baseline)), 6)
        ratings[team] = {"defense": defense, "offense": offense}
    return ratings


class NflverseScheduleProvider:
    """Build the application's schedule payload from public nflverse releases."""

    schedule_url = SCHEDULE_URL

    def __init__(self, fetch_text: Callable[[str], str] = _download) -> None:
        self.fetch_text = fetch_text

    def schedule(self, season: int) -> dict[str, Any]:
        games = _schedule_games(self.fetch_text(SCHEDULE_URL), season)
        rating_season = season - 1
        ratings = _opponent_ratings(self.fetch_text(STATS_URL.format(season=rating_season)), rating_season)
        return {
            "season": season,
            "source": "nflverse",
            "games": games,
            "opponent_ratings": ratings,
        }
