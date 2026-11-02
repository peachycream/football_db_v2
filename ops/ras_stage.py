"""Stage the RAS (ras.football) extract into the raw store: data/raw/ras/maintable/all/<stamp>.csv (+ .meta.json).

Usage: python ops/ras_stage.py <rows.txt> [--site-rows N] [--extracted YYYY-MM-DD]

RAS is Kent Lee Platte's Relative Athletic Score. The site has no export, and a scripted request is refused (HTTP 429), so the table
was paged in the Claude desktop app's browser pane (https://www.ras.football/maintable, 500 rows a page, all 32,683 players) and the
rows kept were the drafted defenders of the 2016-2026 classes: first listed position DE, DT, LB, CB, SS or FS and a draft pick number.
<rows.txt> holds one pipe-separated row per player: YEAR|PICK|RD|POS|RAS|10YD|20YD|40YD|TEAM, POS being the first position the site lists.
This script only turns that file into the raw CSV the loader reads (an em dash, the site's empty cell, becomes an empty field) and
records how it was obtained. Nothing is fetched. The raw store is immutable and never overwritten: a new extract is a new file and
the loader reads the newest.
"""
import csv
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fdb import raw  # noqa: E402

HEADER = ["YEAR", "PICK", "RD", "POS", "RAS", "10YD", "20YD", "40YD", "TEAM"]


def main():
    args = sys.argv[1:]
    src = Path(args[0])
    site_rows = int(args[args.index("--site-rows") + 1]) if "--site-rows" in args else None
    extracted = args[args.index("--extracted") + 1] if "--extracted" in args else None
    rows = [ln.split("|") for ln in src.read_text(encoding="utf-8").splitlines() if ln.strip()]
    bad = [r for r in rows if len(r) != len(HEADER)]
    if bad:
        raise SystemExit(f"{len(bad)} rows without {len(HEADER)} fields, e.g. {bad[0]}")
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(HEADER)
    for r in rows:
        w.writerow(["" if v == "—" else v for v in r])
    payload = buf.getvalue().encode("utf-8")
    params = {"url": "https://www.ras.football/maintable", "method": "browser pane, paged table, 500 rows a page; scripted requests are refused (429)",
              "site_rows": site_rows, "extracted": extracted, "kept": "drafted defenders, classes 2016-2026, first position DE/DT/LB/CB/SS/FS",
              "pos_is_first_listed_position": True, "empty_cell": "em dash -> empty field"}
    rec = raw.write("ras", "maintable", "all", payload, "csv", params, row_count=len(rows), is_final=True)
    print(rec.path, rec.row_count, rec.sha256)


if __name__ == "__main__":
    main()
