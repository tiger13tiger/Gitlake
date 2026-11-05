"""Aggregate the silver sales table into a business-ready gold summary."""
import os
from datetime import date, datetime, timezone

import pandas as pd
from deltalake import DeltaTable, write_deltalake

from _runlog import log_run


def aggregate(silver: pd.DataFrame) -> pd.DataFrame:
    return (
        silver.groupby("order_date", as_index=False)
        .agg(order_count=("order_id", "nunique"), revenue=("amount", "sum"))
        .sort_values("order_date")
    )


def abfss(account: str, container: str, path: str) -> str:
    return f"abfss://{container}@{account}.dfs.core.windows.net/{path}"


def main() -> None:
    account = os.environ["ADLS_ACCOUNT_NAME"]
    run_date = os.environ.get("RUN_DATE") or date.today().isoformat()
    options = {
        "azure_storage_account_name": account,
        "azure_storage_use_azure_cli": "true",
    }

    started_at = datetime.now(timezone.utc)

    silver_path = abfss(account, "silver", "sales")
    gold_path = abfss(account, "gold", "sales_daily_summary")

    silver = DeltaTable(silver_path, storage_options=options).to_pandas()
    gold = aggregate(silver)

    write_deltalake(gold_path, gold, mode="overwrite", storage_options=options)
    print(f"wrote {len(gold)} rows to {gold_path}")
    log_run("silver_to_gold", run_date, len(gold), started_at)


if __name__ == "__main__":
    main()
