"""Shared plumbing for loaders whose source is a CSV file over HTTP."""
import csv
import io

from .. import http
from ..loader import Loader, Scope


class CsvLoader(Loader):
    ext = "csv"
    url_template = ""  # may contain {season}

    def url(self, partition: str) -> str:
        return self.url_template.format(season=partition)

    def fetch(self, partition):
        u = self.url(partition)
        return http.get(u), {"url": u}

    def parse(self, payload: bytes):
        reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
        rows = list(reader)
        return list(reader.fieldnames or []), rows


class SnapshotCsvLoader(CsvLoader):
    """A whole-file, current-state feed: one scope, never final, re-fetched every run."""
    grain = "snapshot"

    def partition(self, scope):
        return "all"

    def scope_rows(self, rows, scope):
        return rows

    def scope_where(self, scope):
        return "1 = 1", ()

    def raw_is_final(self, conn, partition):
        return False
