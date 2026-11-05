"""Aggregate the silver sales table into a business-ready gold summary."""
import os
from datetime import date, datetime, timezone

from deltalake import DeltaTable, write_deltalake

from _runlog import log_run

ACCOUNT = os.environ["ADLS_ACCOUNT_NAME"]
RUN_DATE = os.environ.get("RUN_DATE") or date.today().isoformat()


def abfss(container: str, path: str) -> str:
    return f"abfss://{container}@{ACCOUNT}.dfs.core.windows.net/{path}"


def main() -> None:
    started_at = datetime.now(timezone.utc)
    read_options = {
        "azure_storage_account_name": ACCOUNT,
        "azure_storage_use_azure_cli": "true",
    }

    silver_path = abfss("silver", "sales")
    gold_path = abfss("gold", "sales_daily_summary")

    silver = DeltaTable(silver_path, storage_options=read_options).to_pandas()

    gold = (
        silver.groupby("order_date", as_index=False)
        .agg(order_count=("order_id", "nunique"), revenue=("amount", "sum"))
        .sort_values("order_date")
    )

    write_deltalake(
        gold_path,
        gold,
        mode="overwrite",
        storage_options=read_options,
    )
    print(f"wrote {len(gold)} rows to {gold_path}")
    log_run("silver_to_gold", RUN_DATE, len(gold), started_at)


if __name__ == "__main__":
    main()
