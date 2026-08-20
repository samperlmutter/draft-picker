from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    sleeper_league_id: str
    participant_username: str
    poll_interval_seconds: float = 5
    external_refresh_interval_seconds: float = 1800


def load_config(path: str | None = None) -> Config:
    configured = path or os.environ.get("DRAFT_ADVISOR_CONFIG")
    candidate = Path(configured) if configured else Path("draft-advisor.json")
    try:
        data = json.loads(candidate.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read configuration {candidate}: {exc}") from exc
    required = ("sleeper_league_id", "participant_username")
    missing = [key for key in required if not data.get(key)]
    if missing:
        raise ValueError(f"configuration is missing: {', '.join(missing)}")
    allowed = set(Config.__dataclass_fields__)
    config = Config(**{key: value for key, value in data.items() if key in allowed})
    if config.poll_interval_seconds <= 0 or config.external_refresh_interval_seconds <= 0:
        raise ValueError("refresh intervals must be positive")
    return config
