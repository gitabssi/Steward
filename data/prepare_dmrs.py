#!/usr/bin/env python3
"""Stream-filter the raw DMR files into compact, BigQuery-ready extracts.

Each npdes_dmrs_fyYYYY.zip holds a single ~10 GB CSV. This script reads the
CSV straight out of the zip (nothing is ever unpacked to disk), keeps only
rows that carry an actual reported measurement, projects the 20 columns the
backtest needs, normalizes dates to ISO, and writes one gzipped CSV per year
into data/work/.

Kept row = a real reported value:
  - DMR_VALUE_STANDARD_UNITS is numeric (the measurement, in standard units)
  - no NODI code (NODI = "no data indicator" — the value box was empty)

Enforceable-vs-monitoring filtering (LIMIT_TYPE_CODE = 'ENF') is deliberately
NOT applied here: the forecaster trains on every reported value, while the
scoring SQL counts an exceedance only against enforceable limits. Both need
the same extract, so the flag travels along as a column.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import sys
import time
import zipfile
from pathlib import Path

RAW = Path(__file__).parent / "raw"
WORK = Path(__file__).parent / "work"

# Projection: enough to (1) build monthly series per facility × outfall ×
# parameter × statistical base, (2) know the enforceable limit in force on
# the row, (3) know when the regulator actually received the value.
COLUMNS = [
    "EXTERNAL_PERMIT_NMBR",
    "PERM_FEATURE_NMBR",
    "MONITORING_LOCATION_CODE",
    "PARAMETER_CODE",
    "PARAMETER_DESC",
    "STATISTICAL_BASE_CODE",
    "STATISTICAL_BASE_TYPE_CODE",
    "VALUE_TYPE_CODE",
    "LIMIT_VALUE_TYPE_CODE",
    "LIMIT_VALUE_STANDARD_UNITS",
    "LIMIT_VALUE_QUALIFIER_CODE",
    "STANDARD_UNIT_DESC",
    "LIMIT_TYPE_CODE",
    "MONITORING_PERIOD_END_DATE",
    "DMR_VALUE_STANDARD_UNITS",
    "DMR_VALUE_QUALIFIER_CODE",
    "VALUE_RECEIVED_DATE",
    "EXCEEDENCE_PCT",
    "VIOLATION_CODE",
    "NODI_CODE",
]

DATE_COLUMNS = {"MONITORING_PERIOD_END_DATE", "VALUE_RECEIVED_DATE"}


def iso(us_date: str) -> str:
    """MM/DD/YYYY → YYYY-MM-DD (empty stays empty)."""
    if not us_date:
        return ""
    m, d, y = us_date.split("/")
    return f"{y}-{m}-{d}"


def is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def prepare_year(year: int) -> None:
    src = RAW / f"npdes_dmrs_fy{year}.zip"
    dest = WORK / f"dmrs_fy{year}.csv.gz"
    if dest.exists():
        print(f"  ✓ fy{year} already prepared")
        return
    if not src.exists():
        print(f"  ! {src.name} missing — run data/pull_epa.py first")
        return

    t0 = time.time()
    kept = total = 0
    tmp = dest.with_suffix(".part")
    with zipfile.ZipFile(src) as zf:
        inner = zf.namelist()[0]
        with (
            zf.open(inner) as raw,
            io.TextIOWrapper(io.BufferedReader(raw, 1 << 20), encoding="utf-8", errors="replace") as text,
            gzip.open(tmp, "wt", newline="", compresslevel=6) as gz,
        ):
            reader = csv.reader(text)
            header = next(reader)
            idx = [header.index(c) for c in COLUMNS]
            i_value = header.index("DMR_VALUE_STANDARD_UNITS")
            i_nodi = header.index("NODI_CODE")
            date_pos = [n for n, c in enumerate(COLUMNS) if c in DATE_COLUMNS]

            writer = csv.writer(gz)
            writer.writerow(COLUMNS)
            for row in reader:
                total += 1
                if row[i_nodi] or not row[i_value] or not is_number(row[i_value]):
                    continue
                out = [row[i] for i in idx]
                for n in date_pos:
                    out[n] = iso(out[n])
                writer.writerow(out)
                kept += 1
    tmp.rename(dest)
    mb = dest.stat().st_size / 1e6
    print(
        f"  fy{year}: kept {kept:,} of {total:,} rows "
        f"({mb:.0f} MB gz, {time.time() - t0:.0f}s)"
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--years", default="2020-2025")
    args = p.parse_args()
    lo, _, hi = args.years.partition("-")

    WORK.mkdir(parents=True, exist_ok=True)
    for year in range(int(lo), int(hi or lo) + 1):
        prepare_year(year)
    print("Done. Next: python data/load_bigquery.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
