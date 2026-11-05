"""Shared helper: record one row per completed pipeline stage.

This is the pipeline's own audit trail — independent of GitHub Actions'
log retention window, and queryable the same way as the real data.
Only successful stages log here; a stage that raises is caught by the
workflow's failure-issue step instead, not by this table.
"""
import os
from datetime import datetime, timezone

import pandas as pd
from deltalake import write_deltalake

ACCOUNT = os.environ["ADLS_ACCOUNT_NAME"]

STORAGE_OPTIONS = {
    "azure_storage_account_name": ACCOUNT,
    "azure_storage_use_azure_cli": "true",
}


def log_run(stage: str, run_date: str, rows_written: int, started_at: datetime) -> None:
    finished_at = datetime.now(timezone.utc)
    row = pd.DataFrame([{
        "stage": stage,
        "run_date": run_date,
        "rows_written": rows_written,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": (finished_at - started_at).total_seconds(),
    }])
    path = f"abfss://meta@{ACCOUNT}.dfs.core.windows.net/run_log"
    write_deltalake(path, row, mode="append", storage_options=STORAGE_OPTIONS)
