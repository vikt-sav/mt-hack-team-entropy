from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Settings:
    ingest: dict
    schedule: dict
    target: dict
    model: dict
    inference: dict
    api: dict

    @classmethod
    def load(cls, path: Path | str | None = None) -> "Settings":
        p = Path(path) if path else ROOT / "config" / "settings.yaml"
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
        return cls(**raw)
