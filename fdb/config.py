"""Paths and constants. Every path can be overridden by env var (tests, side copies)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("FDB_DB_PATH", ROOT / "database" / "fdb.db"))
RAW_DIR = Path(os.environ.get("FDB_RAW_DIR", ROOT / "data" / "raw"))
SCHEMA_DIR = ROOT / "schema"
CONTRACTS_DIR = ROOT / "contracts"
REGISTRY_PATH = ROOT / "registry" / "sources.toml"
APP_STATE_DIR = Path(os.environ.get("FDB_APP_STATE_DIR", ROOT / "app_state"))
STATUS_PATH = Path(os.environ.get("FDB_STATUS_PATH", ROOT / "PIPELINE_STATUS.json"))
ENV_PATH = ROOT / ".env"

FIRST_SEASON = 2016
# A game is treated as over GAME_HOURS after kickoff; its week is final
# SETTLE_HOURS after that (sources re-chart immediately after games).
GAME_HOURS = 4
SETTLE_HOURS = 24
# A weekly run still marked "running" after this long is reported as dead.
STALE_RUN_HOURS = 6


def env(name: str, default: str = "") -> str:
    """A secret/setting from the environment, else from .env (gitignored). Never logged."""
    val = os.environ.get(name, "")
    if not val and ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.startswith(f"{name}="):
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
    return val or default
