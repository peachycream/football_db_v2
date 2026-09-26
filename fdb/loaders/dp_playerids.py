"""DynastyProcess db_playerids.csv -> core_dp_playerids. See schema/004 for why it is distrusted."""
from .csvbase import SnapshotCsvLoader


class DpPlayerIdsLoader(SnapshotCsvLoader):
    id = "dynastyprocess.playerids"
    source = "dynastyprocess"
    endpoint = "playerids"
    table = "core_dp_playerids"
    url_template = "https://raw.githubusercontent.com/dynastyprocess/data/master/files/db_playerids.csv"
    MIN_ROWS = 10000  # 12,508 at first load

    def checks(self, conn, scope):
        n = conn.execute("SELECT COUNT(*) FROM core_dp_playerids").fetchone()[0]
        return [] if n >= self.MIN_ROWS else [f"only {n} rows; expected {self.MIN_ROWS:,}+ (truncated download?)"]
