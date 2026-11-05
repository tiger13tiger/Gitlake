"""Land raw data from the Pentana DMS API into bronze, one date per run.

Pentana doesn't publish a public developer API — access is partner-gated,
so PENTANA_API_BASE_URL/PENTANA_API_KEY below and the "vehicles" endpoint
name are placeholders. Once you have real partner credentials and docs,
fill those in and adjust fetch_pages()'s auth header, pagination field
names, and query params to match the real API; normalize()/abfss() should
need no changes for a typical paginated JSON REST endpoint.

This step is skipped automatically (see etl.yml) until PENTANA_API_BASE_URL
is actually set, so merging this doesn't break the existing bronze->silver
pipeline that doesn't depend on it.
"""
import os
from datetime import date

import pandas as pd
import requests
from azure.identity import DefaultAzureCredential


def normalize(records: list[dict]) -> pd.DataFrame:
    return pd.json_normalize(records)


def fetch_pages(base_url: str, api_key: str, endpoint: str, run_date: str) -> list[dict]:
    """Fetch every page of a Pentana endpoint for one date.

    Assumes a JSON body shaped like {"data": [...], "next_page_url": ...|None}
    and bearer-token auth — the common REST convention, not confirmed
    against Pentana's actual API. Adjust to match once you have real docs.
    """
    records: list[dict] = []
    url = f"{base_url}/{endpoint}"
    headers = {"Authorization": f"Bearer {api_key}"}
    params = {"since": run_date}

    while url:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
        records.extend(payload["data"])
        url = payload.get("next_page_url")
        params = None  # a next_page_url, if present, already carries its own query params

    return records


def abfss(account: str, container: str, path: str) -> str:
    return f"abfss://{container}@{account}.dfs.core.windows.net/{path}"


def main() -> None:
    account = os.environ["ADLS_ACCOUNT_NAME"]
    run_date = os.environ.get("RUN_DATE") or date.today().isoformat()
    base_url = os.environ["PENTANA_API_BASE_URL"]
    api_key = os.environ["PENTANA_API_KEY"]

    records = fetch_pages(base_url, api_key, "vehicles", run_date)
    raw = normalize(records)

    bronze_path = abfss(account, "bronze", f"pentana/{run_date}")
    raw.to_parquet(
        bronze_path,
        storage_options={"account_name": account, "credential": DefaultAzureCredential()},
    )
    print(f"landed {len(raw)} rows to {bronze_path}")


if __name__ == "__main__":
    main()
