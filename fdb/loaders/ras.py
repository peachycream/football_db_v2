"""RAS (Relative Athletic Score, ras.football) Main Table -> core_ras_maintable (Phase 17, IDP prospect model).

The site has no export and refuses scripted requests, so there is NO fetch: ops/ras_stage.py puts a hand-paged extract in the raw store
(data/raw/ras/maintable/all/) and this loader only reads it (`fetches = False`), the way a rebuild reads every other raw file. A new
extract is a new immutable raw file; the newest is loaded. Scope: drafted defenders of the 2016-2026 classes (see ops/ras_stage.py).
Keys: YEAR + PICK is the draft year and overall pick, the key the bridge uses against core_nflverse_draft_picks. A name is never read.
"""
import csv
import io

from ..loader import Loader

RENAME = {"10YD": "YD10", "20YD": "YD20", "40YD": "YD40"}   # an identifier cannot start with a digit
KNOWN_DUPLICATES = {(2016, 169)}   # the site lists this pick twice (Lions LB, Buccaneers CB); the bridge rejects both


class RasMaintableLoader(Loader):
    id = "ras.maintable"
    source = "ras"
    endpoint = "maintable"
    table = "core_ras_maintable"
    grain = "snapshot"
    ext = "csv"
    fetches = False
    warn_new_fields = False
    min_rows = 1200   # 1,404 at first staging (2016-2026 drafted defenders)

    def partition(self, scope):
        return "all"

    def parse(self, payload: bytes):
        reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
        fields = list(reader.fieldnames or [])
        rows = [{RENAME.get(k, k): v for k, v in r.items()} for r in reader]
        return fields, rows

    def scope_rows(self, rows, scope):
        return rows

    def scope_where(self, scope):
        return "1 = 1", ()

    def raw_is_final(self, conn, partition):
        return True

    def checks(self, conn, scope):
        fails = []
        n = conn.execute("SELECT COUNT(*) FROM core_ras_maintable").fetchone()[0]
        if n < self.min_rows:
            fails.append(f"only {n} RAS rows; expected {self.min_rows:,}+ (truncated extract?)")
        lo, hi = conn.execute("SELECT MIN(YEAR), MAX(YEAR) FROM core_ras_maintable").fetchone()
        if lo != 2016 or hi < 2026:
            fails.append(f"years run {lo}-{hi}, expected 2016-2026")
        bad = conn.execute("SELECT COUNT(*) FROM core_ras_maintable WHERE PICK NOT BETWEEN 1 AND 262 OR RD NOT BETWEEN 1 AND 7 "
                           "OR RAS NOT BETWEEN 0 AND 10 OR YD10 NOT BETWEEN 1.2 AND 2.3 OR YD20 NOT BETWEEN 2.0 AND 3.6 "
                           "OR YD40 NOT BETWEEN 4.0 AND 6.0").fetchone()[0]
        if bad:
            fails.append(f"{bad} rows with an implausible pick, round, score, split or forty")
        dups = {tuple(r) for r in conn.execute("SELECT YEAR, PICK FROM core_ras_maintable GROUP BY YEAR, PICK HAVING COUNT(*) > 1")}
        if dups - KNOWN_DUPLICATES:
            fails.append(f"(year, pick) listed twice and not a known exception: {sorted(dups - KNOWN_DUPLICATES)[:5]}")
        # a faster 10-yard split cannot come with a slower 20-yard split than 40-yard-dash time allows: 10 <= 20 <= 40
        bad = conn.execute("SELECT COUNT(*) FROM core_ras_maintable WHERE (YD10 IS NOT NULL AND YD20 IS NOT NULL AND YD10 >= YD20) "
                           "OR (YD20 IS NOT NULL AND YD40 IS NOT NULL AND YD20 >= YD40)").fetchone()[0]
        if bad:
            fails.append(f"{bad} rows whose 10-yard split, 20-yard split and forty are not increasing")
        return fails


LOADERS = (RasMaintableLoader,)
