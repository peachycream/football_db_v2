"""nflverse players.csv -> core_nflverse_players (the primary identity source)."""
from .csvbase import SnapshotCsvLoader


class PlayersLoader(SnapshotCsvLoader):
    id = "nflverse.players"
    source = "nflverse"
    endpoint = "players"
    table = "core_nflverse_players"
    url_template = "https://github.com/nflverse/nflverse-data/releases/download/players/players.csv"
    MIN_ROWS = 20000  # 24,830 at first load; fewer means a truncated download

    def checks(self, conn, scope):
        fails = []
        n = conn.execute("SELECT COUNT(*) FROM core_nflverse_players").fetchone()[0]
        if n < self.MIN_ROWS:
            fails.append(f"only {n} players; expected {self.MIN_ROWS:,}+ (truncated download?)")
        for col in ("pff_id", "pfr_id", "espn_id", "otc_id", "nfl_id"):
            dup = conn.execute(f"SELECT COUNT(*) FROM (SELECT {col} FROM core_nflverse_players WHERE {col} IS NOT NULL "
                               f"GROUP BY {col} HAVING COUNT(*) > 1)").fetchone()[0]
            if dup:
                fails.append(f"{col}: {dup} ids shared by more than one gsis_id")  # was 0 for all five at first load
        return fails
