"""Point every configured path at a temp dir so tests never touch real data."""
import shutil
import tempfile
from pathlib import Path

from fdb import config, db, http

FIXTURES = Path(__file__).parent / "fixtures"


class TempEnv:
    def __enter__(self):
        self.dir = Path(tempfile.mkdtemp(prefix="fdb_test_"))
        self.saved = {k: getattr(config, k) for k in ("DB_PATH", "RAW_DIR", "APP_STATE_DIR", "STATUS_PATH")}
        config.DB_PATH = self.dir / "database" / "fdb.db"
        config.RAW_DIR = self.dir / "raw"
        config.APP_STATE_DIR = self.dir / "app_state"
        config.STATUS_PATH = self.dir / "PIPELINE_STATUS.json"
        self.net = http.NETWORK_ENABLED
        return self

    def conn(self):
        c = db.connect()
        db.apply_schema(c)
        return c

    def __exit__(self, *exc):
        for k, v in self.saved.items():
            setattr(config, k, v)
        http.NETWORK_ENABLED = self.net
        shutil.rmtree(self.dir, ignore_errors=True)


def seed_schedule_raw(text: str | None = None, is_final: bool = False):
    """Write a schedule raw file as if it had been fetched."""
    from fdb import raw
    payload = (text if text is not None else (FIXTURES / "games_2025_2026.csv").read_text()).encode()
    n = payload.decode().count("\n") - 1
    return raw.write("nflverse", "schedules", "all", payload, "csv", {"fixture": True}, n, is_final)
