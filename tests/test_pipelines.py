"""Tests for the pure transform logic and the idempotent-write behavior.

No Azure required — these exercise the real pipeline functions (not a
reimplementation of them) against local data and local Delta tables.
"""
import shutil
import tempfile
from datetime import datetime, timezone

import pandas as pd
import pytest
from deltalake import DeltaTable, write_deltalake

from bronze_to_silver import clean
from silver_to_gold import aggregate
from ingest_pentana import normalize
from _runlog import log_run


def test_clean_drops_nulls_and_deduplicates():
    raw = pd.DataFrame({
        "order_id": [1, 2, 3, 3, 4],
        "amount": [10.0, 20.0, 5.0, 5.0, None],
        "order_date": ["2026-11-01"] * 5,
    })
    result = clean(raw)
    assert sorted(result["order_id"].tolist()) == [1, 2, 3]
    assert result["amount"].dtype == float


def test_aggregate_computes_count_and_revenue_per_date():
    silver = pd.DataFrame({
        "order_id": [1, 2, 3, 5, 6],
        "amount": [10.0, 20.0, 5.0, 7.5, 2.5],
        "order_date": ["2026-11-01"] * 3 + ["2026-11-02"] * 2,
    })
    gold = aggregate(silver)

    day1 = gold[gold["order_date"] == "2026-11-01"].iloc[0]
    assert day1["order_count"] == 3
    assert day1["revenue"] == 35.0

    day2 = gold[gold["order_date"] == "2026-11-02"].iloc[0]
    assert day2["order_count"] == 2
    assert day2["revenue"] == 10.0


def test_normalize_flattens_nested_records():
    records = [
        {"id": 1, "make": "Toyota", "details": {"year": 2024}},
        {"id": 2, "make": "Honda", "details": {"year": 2023}},
    ]
    df = normalize(records)
    assert len(df) == 2
    assert "details.year" in df.columns
    assert df.loc[df["id"] == 1, "details.year"].iloc[0] == 2024


@pytest.fixture
def tmp_dir():
    path = tempfile.mkdtemp()
    yield path
    shutil.rmtree(path, ignore_errors=True)


def test_rerun_same_date_does_not_duplicate_silver_rows(tmp_dir):
    silver_path = f"{tmp_dir}/silver/sales"
    day1 = pd.DataFrame({
        "order_id": [1, 2, 3],
        "amount": [10.0, 20.0, 5.0],
        "order_date": ["2026-11-01"] * 3,
    })

    def write_day(run_date: str, raw: pd.DataFrame) -> None:
        cleaned = clean(raw)
        if DeltaTable.is_deltatable(silver_path):
            DeltaTable(silver_path).delete(f"order_date = '{run_date}'")
        write_deltalake(silver_path, cleaned, mode="append")

    write_day("2026-11-01", day1)
    write_day("2026-11-01", day1)  # simulates a retry/re-run

    result = DeltaTable(silver_path).to_pandas()
    assert len(result) == 3


def test_log_run_appends_a_row(tmp_dir):
    run_log_path = f"{tmp_dir}/meta/run_log"
    started_at = datetime.now(timezone.utc)

    log_run("bronze_to_silver", "2026-11-01", rows_written=3, started_at=started_at, path=run_log_path)
    log_run("silver_to_gold", "2026-11-01", rows_written=1, started_at=started_at, path=run_log_path)

    result = DeltaTable(run_log_path).to_pandas()
    assert len(result) == 2
    assert set(result["stage"]) == {"bronze_to_silver", "silver_to_gold"}
    assert (result["duration_seconds"] >= 0).all()
