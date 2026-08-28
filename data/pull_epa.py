#!/usr/bin/env python3
"""Pull the public EPA ICIS-NPDES record used by Steward.

Downloads, into data/raw/ (gitignored, multi-GB):
  - npdes_dmrs_fyYYYY.zip   one per fiscal year: every Discharge Monitoring
                            Report value reported to EPA/states that year,
                            with the permit limit in force on the same row
                            and a flag separating enforceable limits from
                            monitoring-only rows (LIMIT_TYPE_CODE = 'ENF')
  - npdes_downloads.zip     ICIS facility + permit metadata, including the
                            POTW flag (municipal treatment works)
  - npdes_outfalls_layer.zip  discharge-point coordinates

Source: https://echo.epa.gov/tools/data-downloads (public domain).
Idempotent: files already present with the right size are skipped.
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

BASE = "https://echo.epa.gov/files/echodownloads"
RAW = Path(__file__).parent / "raw"

METADATA_FILES = ["npdes_downloads.zip", "npdes_outfalls_layer.zip"]


def remote_size(url: str) -> int:
    req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(req) as r:
        return int(r.headers.get("Content-Length", 0))


def fetch(name: str) -> None:
    url = f"{BASE}/{name}"
    dest = RAW / name
    expected = remote_size(url)
    if dest.exists() and dest.stat().st_size == expected:
        print(f"  ✓ {name} already present ({expected / 1e6:.0f} MB)")
        return
    print(f"  ↓ {name} ({expected / 1e6:.0f} MB)")
    tmp = dest.with_suffix(".part")
    urllib.request.urlretrieve(url, tmp)
    tmp.rename(dest)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--years",
        default="2020-2025",
        help="fiscal year range for DMR files, e.g. 2020-2025 (default) or 2024",
    )
    args = p.parse_args()

    lo, _, hi = args.years.partition("-")
    years = range(int(lo), int(hi or lo) + 1)

    RAW.mkdir(parents=True, exist_ok=True)
    print(f"Pulling EPA ICIS-NPDES record into {RAW}/")
    for name in METADATA_FILES + [f"npdes_dmrs_fy{y}.zip" for y in years]:
        fetch(name)
    print("Done. Next: python data/prepare_dmrs.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
