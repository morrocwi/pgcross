"""policy/loader.py — config file loader.

SPEC §10: load_config reads a YAML config file and returns a plain dict.
"""
from __future__ import annotations
import yaml


def load_config(path: str) -> dict:
    """Load a YAML config file. Returns {} if the file is empty."""
    with open(path) as f:
        return yaml.safe_load(f) or {}
