"""Rebuild the flex-position dashboard by hand (the weekly job does this too). Read-only on the DB.
Writes data/flex_position/flex_position.html. Usage:  python analysis/flex_position/build.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from fdb import db, flex_report  # noqa: E402

if __name__ == "__main__":
    path, leagues = flex_report.write(db.connect())
    for l in leagues:
        print(l["name"], l["teams"], "wk", l["through_week"], {k: (v["flex"], v["eligible"]) for k, v in l["groups"].items()})
    print("wrote", path)
