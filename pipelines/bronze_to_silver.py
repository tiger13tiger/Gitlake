"""Clean and dedupe a day's raw bronze data into the silver Delta table."""
import os
from datetime import date, datetime, timedelta, timezone

import pandas as pd
from azure.identity import DefaultAzureCredential
from deltalake import DeltaTable, write_deltalake

from _runlog import log_run


def clean(raw: pd.DataFrame) -> pd.DataFrame:
    return (
        raw.dropna(subset=["order_id", "amount"])
        .drop_duplicates(subset=["order_id"])
        .assign(amount=lambda d: d["amount"].astype(float))
    )


def abfss(account: str, container: str, path: str) -> str:
    return f"abfss://{container}@{account}.dfs.core.windows.net/{path}"


def main() -> None:
    account = os.environ["ADLS_ACCOUNT_NAME"]
    run_date = os.environ.get("RUN_DATE") or (date.today() - timedelta(days=1)).isoformat()
    write_options = {
        "azure_storage_account_name": account,
        "azure_storage_use_azure_cli": "true",
    }

    started_at = datetime.now(timezone.utc)
    credential = DefaultAzureCredential()

    bronze_path = abfss(account, "bronze", f"sales/{run_date}")
    silver_path = abfss(account, "silver", "sales")

    raw = pd.read_parquet(
        bronze_path,
        storage_options={"account_name": account, "credential": credential},
    )

    cleaned = clean(raw)

    # Re-running for the same date must not duplicate rows: drop that
    # date's existing partition before appending the freshly cleaned one.
    if DeltaTable.is_deltatable(silver_path, storage_options=write_options):
        DeltaTable(silver_path, storage_options=write_options).delete(
            f"order_date = '{run_date}'"
        )

    write_deltalake(silver_path, cleaned, mode="append", storage_options=write_options)
    print(f"wrote {len(cleaned)} rows to {silver_path}")
    log_run("bronze_to_silver", run_date, len(cleaned), started_at)


if __name__ == "__main__":
    main()
