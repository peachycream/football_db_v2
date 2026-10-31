"""nflverse draft_picks.csv and combine.csv -> core_nflverse_draft_picks / core_nflverse_combine (Phase 15a, IDP prospect model).

Whole-file snapshots. Joins are by exact id only: draft_picks.pfr_player_id = combine.pfr_id. `cfb_player_id` / `cfb_id` is a
Sports-Reference slug, not a CFBD or PFF id. The source column `to` is not stored (schema/046).
"""
from .csvbase import SnapshotCsvLoader

CHECK_FROM = 2016   # the duplicate-id checks start here: the combine repeats 17 pfr_ids from the 2000s (re-entries), none 2016+


def _dups(conn, table, col, season_col="season"):
    return conn.execute(f"SELECT COUNT(*) FROM (SELECT {col} FROM {table} WHERE {season_col} >= ? AND {col} IS NOT NULL "
                        f"GROUP BY {col} HAVING COUNT(*) > 1)", (CHECK_FROM,)).fetchone()[0]


class DraftPicksLoader(SnapshotCsvLoader):
    id = "nflverse.draft_picks"
    source = "nflverse"
    endpoint = "draft_picks"
    table = "core_nflverse_draft_picks"
    url_template = "https://github.com/nflverse/nflverse-data/releases/download/draft_picks/draft_picks.csv"
    MIN_ROWS = 12000   # 12,927 at first load (1980-2026)

    def checks(self, conn, scope):
        fails = []
        n = conn.execute("SELECT COUNT(*) FROM core_nflverse_draft_picks").fetchone()[0]
        if n < self.MIN_ROWS:
            fails.append(f"only {n} draft picks; expected {self.MIN_ROWS:,}+ (truncated download?)")
        for col in ("gsis_id", "pfr_player_id", "cfb_player_id"):
            d = _dups(conn, self.table, col)
            if d:
                fails.append(f"{col}: {d} ids on more than one draft pick since {CHECK_FROM}")
        return fails


class CombineLoader(SnapshotCsvLoader):
    id = "nflverse.combine"
    source = "nflverse"
    endpoint = "combine"
    table = "core_nflverse_combine"
    url_template = "https://github.com/nflverse/nflverse-data/releases/download/combine/combine.csv"
    MIN_ROWS = 8000   # 8,968 at first load (2000-2026)

    def checks(self, conn, scope):
        fails = []
        n = conn.execute("SELECT COUNT(*) FROM core_nflverse_combine").fetchone()[0]
        if n < self.MIN_ROWS:
            fails.append(f"only {n} combine rows; expected {self.MIN_ROWS:,}+ (truncated download?)")
        d = conn.execute("SELECT COUNT(*) FROM (SELECT pfr_id FROM core_nflverse_combine WHERE season >= ? AND pfr_id IS NOT NULL "
                         "GROUP BY season, pfr_id HAVING COUNT(*) > 1)", (CHECK_FROM,)).fetchone()[0]
        if d:
            fails.append(f"pfr_id: {d} ids listed twice within one combine season since {CHECK_FROM}")
        # the draft table is owned by nflverse.draft_picks; compare only when it is loaded
        bad = conn.execute("""SELECT COUNT(*) FROM core_nflverse_combine c JOIN core_nflverse_draft_picks d ON d.pfr_player_id = c.pfr_id
                              WHERE c.season >= ? AND c.draft_year IS NOT NULL AND c.draft_year != d.season""", (CHECK_FROM,)).fetchone()[0]
        if bad:
            fails.append(f"{bad} combine rows whose draft_year differs from draft_picks.season on the exact pfr_id join")
        return fails
