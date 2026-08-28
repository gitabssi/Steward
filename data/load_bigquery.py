#!/usr/bin/env python3
"""Load the prepared EPA extracts into BigQuery.

Creates dataset `$BQ_DATASET` (default steward_npdes) and loads every
data/work/dmrs_fy*.csv.gz into one partitioned, clustered table:

    <project>.<dataset>.dmrs
      partitioned by month of monitoring_period_end_date
      clustered by external_permit_nmbr, parameter_code

The table is the corpus the backtest runs on (data/sql/), and the corpus
the permit-sentinel agent queries for any facility the fleet is pointed
at. Idempotent per year: a year already loaded is skipped (tracked in the
table's labels).
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from google.cloud import bigquery

WORK = Path(__file__).parent / "work"

SCHEMA = [
    bigquery.SchemaField("external_permit_nmbr", "STRING"),
    bigquery.SchemaField("perm_feature_nmbr", "STRING"),
    bigquery.SchemaField("monitoring_location_code", "STRING"),
    bigquery.SchemaField("parameter_code", "STRING"),
    bigquery.SchemaField("parameter_desc", "STRING"),
    bigquery.SchemaField("statistical_base_code", "STRING"),
    bigquery.SchemaField("statistical_base_type_code", "STRING"),
    bigquery.SchemaField("value_type_code", "STRING"),
    bigquery.SchemaField("limit_value_type_code", "STRING"),
    bigquery.SchemaField("limit_value_standard_units", "FLOAT64"),
    bigquery.SchemaField("limit_value_qualifier_code", "STRING"),
    bigquery.SchemaField("standard_unit_desc", "STRING"),
    bigquery.SchemaField("limit_type_code", "STRING"),
    bigquery.SchemaField("monitoring_period_end_date", "DATE"),
    bigquery.SchemaField("dmr_value_standard_units", "FLOAT64"),
    bigquery.SchemaField("dmr_value_qualifier_code", "STRING"),
    bigquery.SchemaField("value_received_date", "DATE"),
    bigquery.SchemaField("exceedence_pct", "FLOAT64"),
    bigquery.SchemaField("violation_code", "STRING"),
    bigquery.SchemaField("nodi_code", "STRING"),
]


def main() -> int:
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project:
        print("Set GOOGLE_CLOUD_PROJECT (see .env.example)")
        return 1
    dataset_id = f"{project}.{os.environ.get('BQ_DATASET', 'steward_npdes')}"
    client = bigquery.Client(project=project)

    dataset = bigquery.Dataset(dataset_id)
    dataset.location = os.environ.get("BQ_LOCATION", "US")
    dataset.description = (
        "Public EPA ICIS-NPDES Discharge Monitoring Report extract. "
        "Source: https://echo.epa.gov/tools/data-downloads (public domain). "
        "Loaded by data/load_bigquery.py."
    )
    client.create_dataset(dataset, exists_ok=True)

    table_id = f"{dataset_id}.dmrs"
    try:
        table = client.get_table(table_id)
        loaded = set((table.labels or {}).get("years_loaded", "").split("-"))
    except Exception:
        table = bigquery.Table(table_id, schema=SCHEMA)
        table.time_partitioning = bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.MONTH,
            field="monitoring_period_end_date",
        )
        table.clustering_fields = ["external_permit_nmbr", "parameter_code"]
        table = client.create_table(table)
        loaded = set()

    files = sorted(WORK.glob("dmrs_fy*.csv.gz"))
    if not files:
        print("Nothing in data/work/ — run data/prepare_dmrs.py first")
        return 1

    job_config = bigquery.LoadJobConfig(
        schema=SCHEMA,
        skip_leading_rows=1,
        source_format=bigquery.SourceFormat.CSV,
        allow_quoted_newlines=True,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
    )

    for path in files:
        year = re.search(r"fy(\d{4})", path.name).group(1)
        if year in loaded:
            print(f"  ✓ fy{year} already loaded")
            continue
        print(f"  ↥ loading {path.name} ({path.stat().st_size / 1e6:.0f} MB gz)")
        with path.open("rb") as fh:
            job = client.load_table_from_file(fh, table_id, job_config=job_config)
        job.result()
        loaded.add(year)
        table.labels = {"years_loaded": "-".join(sorted(x for x in loaded if x))}
        client.update_table(table, ["labels"])
        print(f"    fy{year}: {job.output_rows:,} rows")

    table = client.get_table(table_id)
    print(f"Total: {table.num_rows:,} rows in {table_id}")
    print("Next: run the backtest — see data/sql/README.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
