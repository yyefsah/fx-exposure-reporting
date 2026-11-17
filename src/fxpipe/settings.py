"""Chargement de la configuration YAML."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def load(path: str | Path | None = None) -> dict:
    path = Path(path) if path else ROOT / "config" / "settings.yaml"
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    cfg["_root"] = ROOT
    return cfg
