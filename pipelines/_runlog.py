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


def log_run(
    stage: str,
    run_date: str,
    rows_written: int,
    started_at: datetime,
    *,
    path: str | None = None,
) -> None:
    """Append one row to meta/run_log.

    `path` is only ever overridden by tests, to point at a local Delta
    table instead of ADLS — production call sites always omit it.
    """
    finished_at = datetime.now(timezone.utc)
    row = pd.DataFrame([{
        "stage": stage,
        "run_date": run_date,
        "rows_written": rows_written,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": (finished_at - started_at).total_seconds(),
    }])

    if path is not None:
        write_deltalake(path, row, mode="append")
        return

    account = os.environ["ADLS_ACCOUNT_NAME"]
    target = f"abfss://meta@{account}.dfs.core.windows.net/run_log"
    write_deltalake(
        target,
        row,
        mode="append",
        storage_options={
            "azure_storage_account_name": account,
            "azure_storage_use_azure_cli": "true",
        },
    )
