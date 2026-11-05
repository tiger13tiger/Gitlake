"""Land raw CRM data from Salesforce into bronze, one date per run.

Unlike Pentana, Salesforce's REST API is public and stable, so the auth
flow and query mechanics below are real, not guesses — what's still a
placeholder is the object/fields in the SOQL query (swap "Account" for
whatever CRM object you actually need) and your org's Connected App
credentials.

Auth: OAuth 2.0 Client Credentials flow — the standard approach for an
unattended, scheduled integration (no interactive user). Set this up in
Salesforce Setup -> App Manager -> New Connected App -> enable OAuth,
enable "Client Credentials Flow", and assign a running user. That gives
you SALESFORCE_CLIENT_ID / SALESFORCE_CLIENT_SECRET.

This step is skipped automatically (see etl.yml) until
SALESFORCE_LOGIN_URL is actually set, so merging this doesn't affect the
existing pipeline before real credentials exist.
"""
import os
from datetime import date

import pandas as pd
import requests
from azure.identity import DefaultAzureCredential
from requests.auth import HTTPBasicAuth

API_VERSION = "v59.0"  # bump to your org's current version if you like; old ones stay supported


def get_access_token(login_url: str, client_id: str, client_secret: str) -> tuple[str, str]:
    """Returns (access_token, instance_url)."""
    response = requests.post(
        f"{login_url}/services/oauth2/token",
        data={"grant_type": "client_credentials"},
        auth=HTTPBasicAuth(client_id, client_secret),
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    return payload["access_token"], payload["instance_url"]


def fetch_records(instance_url: str, access_token: str, soql: str) -> list[dict]:
    """Runs a SOQL query and follows nextRecordsUrl until done."""
    records: list[dict] = []
    headers = {"Authorization": f"Bearer {access_token}"}
    url = f"{instance_url}/services/data/{API_VERSION}/query"
    params = {"q": soql}

    while url:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
        records.extend(payload["records"])
        next_path = payload.get("nextRecordsUrl")
        url = f"{instance_url}{next_path}" if next_path else None
        params = None  # nextRecordsUrl already carries its own query string

    return records


def normalize(records: list[dict]) -> pd.DataFrame:
    # every Salesforce record carries an "attributes" metadata field
    # (object type + API url) that isn't part of the actual data
    cleaned = [{k: v for k, v in r.items() if k != "attributes"} for r in records]
    return pd.json_normalize(cleaned)


def abfss(account: str, container: str, path: str) -> str:
    return f"abfss://{container}@{account}.dfs.core.windows.net/{path}"


def main() -> None:
    account = os.environ["ADLS_ACCOUNT_NAME"]
    run_date = os.environ.get("RUN_DATE") or date.today().isoformat()
    login_url = os.environ["SALESFORCE_LOGIN_URL"]
    client_id = os.environ["SALESFORCE_CLIENT_ID"]
    client_secret = os.environ["SALESFORCE_CLIENT_SECRET"]

    access_token, instance_url = get_access_token(login_url, client_id, client_secret)

    # swap "Account" and the field list for the real CRM object you need
    soql = (
        f"SELECT Id, Name, SystemModstamp FROM Account "
        f"WHERE DAY_ONLY(SystemModstamp) = {run_date}"
    )
    records = fetch_records(instance_url, access_token, soql)
    raw = normalize(records)

    bronze_path = abfss(account, "bronze", f"salesforce/{run_date}")
    raw.to_parquet(
        bronze_path,
        storage_options={"account_name": account, "credential": DefaultAzureCredential()},
    )
    print(f"landed {len(raw)} rows to {bronze_path}")


if __name__ == "__main__":
    main()
