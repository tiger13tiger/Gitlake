# GitLake

[![medallion-etl](https://github.com/tiger13tiger/Gitlake/actions/workflows/etl.yml/badge.svg?branch=main)](https://github.com/tiger13tiger/Gitlake/actions/workflows/etl.yml)
[![ci](https://github.com/tiger13tiger/Gitlake/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/tiger13tiger/Gitlake/actions/workflows/ci.yml)

A medallion-architecture lakehouse driven by GitHub Actions: code and orchestration live in this repo, data lives in Azure Data Lake Storage Gen2 as Delta tables, moving bronze → silver → gold on a schedule.

![GitLake pipeline map](docs/architecture.svg)

Each run: the Actions runner checks out this repo, trades a GitHub OIDC token for Azure access (no stored secret), optionally fetches from the Pentana DMS API and/or Salesforce CRM and lands them to bronze, reads bronze, writes silver, reads silver back, writes gold — then the VM is destroyed. Only this repo and the storage account persist between runs.

## Layout

```
.github/workflows/etl.yml      # schedule + job steps + failure alerting
.github/workflows/ci.yml       # lint + test on every push to main / pull request
pipelines/ingest_pentana.py    # land raw data from the Pentana DMS API into bronze
pipelines/ingest_salesforce.py # land raw CRM data from Salesforce into bronze
pipelines/bronze_to_silver.py  # clean/dedupe raw bronze into silver
pipelines/silver_to_gold.py    # aggregate silver into gold
pipelines/_runlog.py           # shared helper: appends one row per successful stage
tests/test_pipelines.py        # tests for the above — no Azure required
conftest.py                    # makes pipelines/ importable the same way the workflow runs it
requirements.txt
requirements-dev.txt           # requirements.txt + pytest + ruff, for CI only
docs/architecture.svg
```

Data itself is **not** in this repo — it lives in ADLS Gen2, as Delta tables under four containers/paths:

- `bronze/` — raw data, landed as received, append-only (`bronze/sales/...` from wherever that already lands; `bronze/pentana/...` from `ingest_pentana.py`; `bronze/salesforce/...` from `ingest_salesforce.py`)
- `silver/` — cleaned, deduped, typed
- `gold/` — aggregated, business-ready tables your dashboards query
- `meta/run_log` — one row per successful stage run (`stage`, `run_date`, `rows_written`, `started_at`, `finished_at`, `duration_seconds`) — the pipeline's own audit trail, independent of GitHub's log retention

### Pentana DMS source

`pipelines/ingest_pentana.py` is a **scaffold, not a tested integration** — Pentana doesn't publish a public developer API; access is partner-gated, so there's no base URL, auth scheme, or endpoint schema to build against yet. The script assumes a generic paginated-JSON-over-bearer-token shape (the common REST convention), which will very likely need adjusting once you have real docs from Pentana.

It's wired into `etl.yml` but **skipped automatically** until you set `PENTANA_API_BASE_URL` — so merging this doesn't touch the pipeline you already have working. Once you have real partner credentials:
1. Set repo variable `PENTANA_API_BASE_URL` and secret `PENTANA_API_KEY`.
2. Adjust `fetch_pages()`'s auth header, pagination field names, and the `"vehicles"` endpoint name in `ingest_pentana.py` to match Pentana's actual API.
3. The step then runs automatically on the next scheduled or manual run.

### Salesforce CRM source

`pipelines/ingest_salesforce.py` is on firmer ground than the Pentana one — Salesforce's REST API is public and stable, so the OAuth 2.0 Client Credentials flow, the `/services/data/<version>/query` endpoint, and the `nextRecordsUrl` pagination it uses are real, documented behavior, not guesses. What's still a placeholder is the SOQL query itself (`SELECT Id, Name, SystemModstamp FROM Account WHERE ...` — swap for your real CRM object and fields) and your org's Connected App credentials.

To wire up real access:
1. In Salesforce Setup → App Manager → New Connected App: enable OAuth, enable **Client Credentials Flow**, and assign a running user (this flow needs no interactive login — the right fit for a scheduled job).
2. Set repo variable `SALESFORCE_LOGIN_URL` (e.g. your org's My Domain URL) and secrets `SALESFORCE_CLIENT_ID` / `SALESFORCE_CLIENT_SECRET`.
3. Replace the SOQL query in `ingest_salesforce.py` with the object/fields you actually need.

Same safety pattern as Pentana: this step is skipped automatically until `SALESFORCE_LOGIN_URL` is set.

## Setup

1. **Storage account** — create an ADLS Gen2 account (hierarchical namespace enabled) with containers `bronze`, `silver`, `gold`, `meta`.

2. **Azure AD app registration** — create an app registration and add a federated credential that trusts GitHub's OIDC tokens for this repo:
   - Issuer: `https://token.actions.githubusercontent.com`
   - Subject: `repo:tiger13tiger/Gitlake:ref:refs/heads/main` (match the repo's exact casing; use `:environment:<name>` instead if you deploy via a GitHub Environment)

3. **Role assignment** — grant that app's service principal the **Storage Blob Data Contributor** role, scoped to the storage account.

4. **Repo configuration**:
   - Secrets: `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`
   - Variable: `ADLS_ACCOUNT_NAME` (the storage account name — not sensitive, so it's a variable, not a secret)

5. Merge this branch to `main`. **The `schedule` trigger only ever fires from the default branch** — the workflow can run from any branch via manual `workflow_dispatch`, but the 03:00 UTC cron does nothing until this is on `main`.

To backfill or re-run a specific day, use `workflow_dispatch` and fill in `run_date` (`YYYY-MM-DD`); leave it blank to process yesterday. Re-running the same date is safe — `bronze_to_silver.py` replaces that date's rows in silver instead of duplicating them.

## Monitoring

- **Status at a glance** — the badge at the top of this README reflects the latest run on `main`.
- **On failure** — the workflow files (or comments on) a single open GitHub issue labeled `pipeline-failure`, linking the failed run. Repeated failures comment on the same issue instead of spawning new ones; close it once you've fixed the cause, and the next failure opens a fresh one.
- **Data health, not just job status** — `meta/run_log` records rows written and duration for every successful stage, and every Delta table also keeps its own write history for free via `DeltaTable(path).history()`. A dashboard, if you build one later, should read from here rather than re-polling GitHub's API.

## Testing

`pipelines/*.py` keep their Azure-reading `main()` separate from the pure transform logic (`clean()`, `aggregate()`), so the logic is testable with no cloud dependency at all — `tests/test_pipelines.py` covers the clean/dedupe rules, the gold aggregation, the idempotent re-run, and the run_log write, all against local data and local Delta tables. `ci.yml` runs `ruff` and this test suite on every push to `main` and every pull request.

When you swap in your real source/schema/aggregation (next section), update these tests alongside — they're what catches a bad change before the 3am run does.

```bash
pip install -r requirements-dev.txt
ruff check pipelines tests
pytest tests -v
```

## What you need to change

Everything else here is meant to be left alone. The only things specific to your data are:

1. **ADLS linking** — the four repo secrets/variable in step 4 above. Nothing else in the workflow or scripts needs touching to point at your storage account.
2. **Source path and schema**, in `pipelines/bronze_to_silver.py`:
   - `abfss(account, "bronze", f"sales/{run_date}")` — your bronze container/prefix layout
   - `order_id`, `amount`, `order_date` — your actual column names, referenced in `clean()` and in the partition-delete predicate
3. **Business aggregation**, in `pipelines/silver_to_gold.py` — `aggregate()` is where your real gold-layer logic goes.
4. **Pentana API specifics**, in `pipelines/ingest_pentana.py`, once you have partner access — see "Pentana DMS source" above.
5. **Salesforce query/credentials**, in `pipelines/ingest_salesforce.py` — see "Salesforce CRM source" above.

## Notes

- `pipelines/*.py` use `pandas` + `deltalake` (delta-rs) rather than PySpark — lighter to install on a GitHub-hosted runner, no JVM startup cost. Swap in PySpark if a stage needs real distributed compute.
- `requirements.txt` is pinned to exact versions that were installed and run against together (clean/dedupe, the idempotent re-run, and the gold aggregation all pass locally against them) — bump deliberately, not by habit.
- The sample transforms (`sales` bronze → silver → gold) are placeholders — replace the read path, cleaning rules, and aggregation with your actual source and business logic.
- Runners are stateless between runs: don't rely on anything written to local disk surviving past the job that wrote it.
