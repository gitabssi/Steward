#!/usr/bin/env python3
"""Extract permit metadata from npdes_downloads.zip → data/work/permits.csv.gz.

Keeps one row per (permit, version) with the fields the backtest scopes
on: the POTW flag (municipal treatment works), design flow (small plants
are the point), major/minor status, and the receiving water's name.
"""

from __future__ import annotations

import csv
import gzip
import io
import sys
import zipfile
from pathlib import Path

RAW = Path(__file__).parent / "raw"
WORK = Path(__file__).parent / "work"

COLUMNS = [
    "EXTERNAL_PERMIT_NMBR",
    "VERSION_NMBR",
    "FACILITY_TYPE_INDICATOR",
    "PERMIT_TYPE_CODE",
    "MAJOR_MINOR_STATUS_FLAG",
    "PERMIT_STATUS_CODE",
    "TOTAL_DESIGN_FLOW_NMBR",
    "STATE_WATER_BODY_NAME",
    "PERMIT_NAME",
    "ISSUING_AGENCY",
    "EFFECTIVE_DATE",
    "EXPIRATION_DATE",
]

DATE_COLUMNS = {"EFFECTIVE_DATE", "EXPIRATION_DATE"}


def iso(us_date: str) -> str:
    if not us_date:
        return ""
    m, d, y = us_date.split("/")
    return f"{y}-{m}-{d}"


def main() -> int:
    src = RAW / "npdes_downloads.zip"
    dest = WORK / "permits.csv.gz"
    if dest.exists():
        print("  ✓ permits already prepared")
        return 0

    WORK.mkdir(parents=True, exist_ok=True)
    kept = 0
    tmp = dest.with_suffix(".part")
    with zipfile.ZipFile(src) as zf:
        with (
            zf.open("ICIS_PERMITS.csv") as raw,
            io.TextIOWrapper(io.BufferedReader(raw, 1 << 20), encoding="utf-8", errors="replace") as text,
            gzip.open(tmp, "wt", newline="", compresslevel=6) as gz,
        ):
            reader = csv.reader(text)
            header = next(reader)
            idx = [header.index(c) for c in COLUMNS]
            date_pos = [n for n, c in enumerate(COLUMNS) if c in DATE_COLUMNS]
            writer = csv.writer(gz)
            writer.writerow(COLUMNS)
            for row in reader:
                # The raw export carries stray NUL bytes and padded blanks
                # in a handful of rows; scrub them or the load rejects.
                out = [row[i].replace("\x00", "").strip() for i in idx]
                for n in date_pos:
                    out[n] = iso(out[n])
                writer.writerow(out)
                kept += 1
    tmp.rename(dest)
    print(f"  permits: {kept:,} rows ({dest.stat().st_size / 1e6:.0f} MB gz)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
