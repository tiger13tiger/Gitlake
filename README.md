# GitLake

[![medallion-etl](https://github.com/tiger13tiger/Gitlake/actions/workflows/etl.yml/badge.svg?branch=main)](https://github.com/tiger13tiger/Gitlake/actions/workflows/etl.yml)
[![ci](https://github.com/tiger13tiger/Gitlake/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/tiger13tiger/Gitlake/actions/workflows/ci.yml)

A medallion-architecture lakehouse driven by GitHub Actions: code and orchestration live in this repo, data lives in Azure Data Lake Storage Gen2 as Delta tables, moving bronze → silver → gold on a schedule.

![GitLake pipeline map](docs/architecture.svg)

Each run: the Actions runner checks out this repo, trades a GitHub OIDC token for Azure access (no stored secret), reads bronze, writes silver, reads silver back, writes gold — then the VM is destroyed. Only this repo and the storage account persist between runs.

## Layout

```
.github/workflows/etl.yml      # schedule + job steps + failure alerting
.github/workflows/ci.yml       # lint + test on every push to main / pull request
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

- `bronze/` — raw data, landed as received, append-only
- `silver/` — cleaned, deduped, typed
- `gold/` — aggregated, business-ready tables your dashboards query
- `meta/run_log` — one row per successful stage run (`stage`, `run_date`, `rows_written`, `started_at`, `finished_at`, `duration_seconds`) — the pipeline's own audit trail, independent of GitHub's log retention

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

## Notes

- `pipelines/*.py` use `pandas` + `deltalake` (delta-rs) rather than PySpark — lighter to install on a GitHub-hosted runner, no JVM startup cost. Swap in PySpark if a stage needs real distributed compute.
- `requirements.txt` is pinned to exact versions that were installed and run against together (clean/dedupe, the idempotent re-run, and the gold aggregation all pass locally against them) — bump deliberately, not by habit.
- The sample transforms (`sales` bronze → silver → gold) are placeholders — replace the read path, cleaning rules, and aggregation with your actual source and business logic.
- Runners are stateless between runs: don't rely on anything written to local disk surviving past the job that wrote it.
