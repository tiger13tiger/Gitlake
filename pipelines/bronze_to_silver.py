"""Clean and dedupe a day's raw bronze data into the silver Delta table."""
import os
from datetime import date, timedelta

import pandas as pd
from azure.identity import DefaultAzureCredential
from deltalake import DeltaTable, write_deltalake

ACCOUNT = os.environ["ADLS_ACCOUNT_NAME"]
RUN_DATE = os.environ.get("RUN_DATE") or (date.today() - timedelta(days=1)).isoformat()

WRITE_OPTIONS = {
    "azure_storage_account_name": ACCOUNT,
    "azure_storage_use_azure_cli": "true",
}


def abfss(container: str, path: str) -> str:
    return f"abfss://{container}@{ACCOUNT}.dfs.core.windows.net/{path}"


def main() -> None:
    credential = DefaultAzureCredential()

    bronze_path = abfss("bronze", f"sales/{RUN_DATE}")
    silver_path = abfss("silver", "sales")

    raw = pd.read_parquet(
        bronze_path,
        storage_options={"account_name": ACCOUNT, "credential": credential},
    )

    clean = (
        raw.dropna(subset=["order_id", "amount"])
        .drop_duplicates(subset=["order_id"])
        .assign(amount=lambda d: d["amount"].astype(float))
    )

    # Re-running for the same date must not duplicate rows: drop that
    # date's existing partition before appending the freshly cleaned one.
    if DeltaTable.is_deltatable(silver_path, storage_options=WRITE_OPTIONS):
        DeltaTable(silver_path, storage_options=WRITE_OPTIONS).delete(
            f"order_date = '{RUN_DATE}'"
        )

    write_deltalake(silver_path, clean, mode="append", storage_options=WRITE_OPTIONS)
    print(f"wrote {len(clean)} rows to {silver_path}")


if __name__ == "__main__":
    main()
