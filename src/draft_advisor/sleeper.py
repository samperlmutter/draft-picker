from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


class SleeperClient:
    base_url = "https://api.sleeper.app/v1"

    def __init__(self) -> None:
        fixtures = os.environ.get("DRAFT_ADVISOR_FIXTURES")
        self.fixtures = Path(fixtures) if fixtures else None

    def get(self, endpoint: str) -> Any:
        if self.fixtures:
            name = endpoint.strip("/").replace("/", "__") + ".json"
            path = self.fixtures / name
            try:
                return json.loads(path.read_text())
            except FileNotFoundError as exc:
                raise ValueError(f"recorded Sleeper response is missing: {name}") from exc
            except json.JSONDecodeError as exc:
                raise ValueError(f"recorded Sleeper response is invalid: {name}") from exc
        request = urllib.request.Request(
            f"{self.base_url}/{endpoint.lstrip('/')}",
            headers={"User-Agent": "draft-advisor/0.1"},
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.load(response)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ValueError(f"Sleeper request failed for {endpoint}: {exc}") from exc

    def user(self, username: str) -> dict[str, Any]:
        value = self.get(f"user/{username}")
        if not isinstance(value, dict) or not value.get("user_id"):
            raise ValueError(f"Sleeper user not found: {username}")
        return value

    def league(self, league_id: str) -> dict[str, Any]:
        return self.get(f"league/{league_id}")

    def league_users(self, league_id: str) -> list[dict[str, Any]]:
        return self.get(f"league/{league_id}/users")

    def rosters(self, league_id: str) -> list[dict[str, Any]]:
        return self.get(f"league/{league_id}/rosters")

    def current_draft(self, league_id: str) -> dict[str, Any]:
        drafts = self.get(f"league/{league_id}/drafts")
        if not drafts:
            raise ValueError(f"no draft found for Sleeper league {league_id}")
        active = [draft for draft in drafts if draft.get("status") != "complete"]
        candidates = active or drafts
        return max(candidates, key=lambda draft: int(draft.get("created", 0) or 0))

    def draft(self, draft_id: str) -> dict[str, Any]:
        return self.get(f"draft/{draft_id}")

    def picks(self, draft_id: str) -> list[dict[str, Any]]:
        return self.get(f"draft/{draft_id}/picks")

    def traded_picks(self, draft_id: str) -> list[dict[str, Any]]:
        return self.get(f"draft/{draft_id}/traded_picks")
