# Sequential learning in Senate prediction markets

Study how unexpected Senate results relate to repricing in unresolved races.
The project uses **Polymarket Gamma for metadata** and the public **Polymarket
CLOB price-history endpoint for probability samples**. No PMXT, sidecar, wallet,
private key, or trading account is needed.

Gamma can return old market listings; this does **not** guarantee price history
for those listings. Coverage is measured per outcome token and requested window.
The initial research design is in [docs/methodology.md](docs/methodology.md), with
data contracts in [docs/schema.md](docs/schema.md).

## What works now

- Discover open and closed Senate-market candidates, with raw response snapshots,
  deterministic pagination, cache replay and explicit partial-scan reporting.
- Fetch outcome-token price histories in bounded date chunks and report first/last
  observations, empty chunks, sampling gaps and failures.
- Validate human-reviewed race/token mappings and timestamped election events.
- Batch nearby calls chronologically within each cycle and election type.
- Build descriptive batch–target–window responses with staleness, unresolved-status,
  sampling-frequency and overlapping-news checks, including an exclusion table.
- Run a fixed-loading Bayesian reference calculation with frozen market priors,
  posterior trajectories and predictive probabilities for remaining races.
- Run an offline synthetic demonstration and statistical correctness tests.

The full fitted hierarchical model, polling/census enrichment, clustered regression,
cross-cycle validation and publication plots are later research phases. No empirical
results are inferred from terminal prices. A partially curated 2024 AP-call dataset
is included; see [event provenance and remaining gaps](docs/event_review.md).

## Setup and offline demonstration

```sh
uv sync
uv run python main.py --help
uv run python main.py demo
uv run pytest
uv run ruff check .
```

`demo` writes explicitly synthetic catalog, histories, event batches, panel and
posterior JSON under `outputs/demo/`. It makes no network requests. After installation,
`uv run senate-market` is equivalent to `uv run python main.py`.

## 1. Discover and review markets

```sh
uv run python scripts/political_events.py --end-year 2024 --max-pages 200 \
  --output data/interim/catalog_2024.json
uv run python scripts/inspect_events.py data/interim/catalog_2024.json
```

Both `closed=true` and `closed=false` are queried explicitly. No active-only filter
is applied. Discovery uses Gamma's `/markets/keyset` cursor pagination, avoiding
the older `/markets` offset limit that returns HTTP 422 on deep scans. Page size
is limited to 100; progress is printed per page. `--end-year` filters the venue's
end-date field, not election year;
late settlements and runoffs may require a wider/unfiltered catalog. `--slug`
accepts an exact **market** slug (repeatable), bypasses text classification, and
still searches both closed/open partitions. `--tag-id` optionally narrows discovery.

The word-based filter can include chamber-control, foreign Senate, state legislature
and primary markets. It can miss candidate-only listings. A complete election
universe needs manual reconciliation against an external Senate race list and exact
slug additions. Exit status 2 means pagination stopped at `--max-pages`: a partial
catalog is still saved and clearly marked. An exhausted filtered scan does not
establish full Senate coverage.

`configs/races.csv` now contains 34 reviewed 2024 mappings from the local catalog.
See [mapping decisions and caveats](docs/race_mapping_review.md). For the current
single-election-type Bayesian reference, pair `configs/races_2024_general.csv`
with `configs/events_2024_general.csv` when building events (33 regular elections,
excluding Nebraska's special election; 30 calls currently sourced).
For other cycles, prepare a mapping using [the template](configs/races.template.csv).
Choose one token per race and explicitly map its probability to a **Democratic win**.
`identity` keeps the token price; `complement` uses `1 - price`. The latter is valid
only if the token is exactly the complement of the defined Democratic-win event.
Candidate labels, independents/caucus affiliation, special races and multi-candidate
contracts require review; `Yes` by itself never establishes party direction.

## 2. Audit price coverage

Probe all catalog outcomes over an explicit period:

```sh
uv run python scripts/fetch_history.py --catalog data/interim/catalog_2024.json \
  --start 2024-11-05T00:00:00Z --end 2024-11-07T00:00:00Z \
  --fidelity 1 --chunk-days 1 --output-dir data/interim/history_2024
```

Use repeatable `--token-id DECIMAL_TOKEN_ID` instead of `--catalog` for a small
reviewed selection. For a broad history audit, start with `--fidelity 60` over
longer periods; re-fetch the election-night window at finer resolution into a
**separate output directory**. The CLI defaults to 60 minutes for broad audits.
The five-minute event study requires finer observed sampling and will exclude
hourly histories. Requesting one-minute fidelity does not prove one-minute coverage.

Inspect `coverage.json`: `observed`, `empty`, and `error` have distinct meanings.
Empty history is never converted into zero probability. A failure returns exit 1
and does not stop other selected tokens. A coverage manifest prevents an old token
file from a failed previous fetch being used by the analysis loader.

Results contain price samples, not OHLCV candles, spreads, depth, volume or a verified
tradable midpoint. Current Gamma liquidity/volume must not become historical controls.
Gamma does not supply race-call timestamps. Historical order-book features would
require a separately audited archive such as Pendulum.

Responses are cached under `data/raw/http/`; `--offline` replays exact requests,
and `--refresh` retrieves new responses. Content-addressed response snapshots remain
available after refresh. Use separate output paths for separate research runs;
normalized outputs at the same path are replaced. Downloads and outputs are gitignored.

## 3. Curate calls and construct batches

`configs/events.csv` contains 31 sourced 2024 AP calls; three call times remain
pending in `configs/events_pending.csv`. See [the event review](docs/event_review.md)
before interpreting outputs. For another cycle, use [the event template](configs/events.template.csv).
Use a timestamped reporting source for calls and official results for outcomes/margins.
Keep poll close, first returns, race call and market settlement as separate records.
Every timestamp must carry a timezone; all are converted to UTC. Date-only events
cannot identify intraday responses. Include overlapping major news in `other_news` rows.

```sh
uv run python main.py events --catalog data/interim/catalog_2024.json \
  --races configs/races.csv --events configs/events.csv \
  --config configs/research.toml --output data/processed/events_2024.json
```

Calls are the default result events. Settlement is allowed only as an explicit
fallback in the configuration. Poll close and first returns never disclose the
eventual binary result. Calls within five minutes of a batch's first call form a
batch; adjacency does not chain into arbitrarily long batches. Batches never mix
cycles or election types. Missing call times are reported as unsequenced races.

For a target with no known-result timestamp, supply a sourced, reviewed
`unresolved_through` time in its race mapping; otherwise the panel excludes it
because missing metadata does not establish that it was unresolved.

## Compare model updates with market changes

After building the general-election panel and posterior, run:

```sh
uv run python scripts/compare_model_market.py \
  --panel outputs/panel_2024_general.json --posterior outputs/posterior_2024.json \
  --output-dir outputs/comparison_2024
```

Read `summary.md` for per-horizon errors, `responses.csv` for matched observations,
and `comparison.json` for full results and provenance. Rerunning replaces these
reports, not their source inputs. The comparison requires matching event and history
hashes; batch IDs alone cannot safely match separate runs.

Model changes use the preceding posterior (or the frozen prior for the first batch),
not the last batch that happened to survive panel exclusions. Current-batch results
are available only at batch end. The zero-change benchmark predicts no market price
movement. MAE is in percentage points, not a Brier score against election outcomes.
Repeated races/batches are dependent observations. This is a descriptive diagnostic,
not out-of-sample validation, a fitted time-decay model, or a causal estimate.

## Offline price-history audit

Before interpreting the panel, generate plots and review flags for the mapped tokens:

```sh
uv run python scripts/audit_history.py --events data/processed/events_2024.json \
  --history-dir data/interim/history_2024 --output-dir outputs/history_audit_2024
open outputs/history_audit_2024/index.html
```

The self-contained HTML report requires no plotting libraries or internet connection.
It plots contract-oriented Democratic-win probabilities with AP-call markers and
reports calls outside each observed span. `audit.json` contains all detected changes,
flat stretches, gaps and input hashes. Available coverage-manifest hashes are checked.
Default review thresholds are adjacent changes of at least 10 percentage points,
identical samples lasting at least 60 minutes, and sampling gaps over 120 seconds.
Override with `--jump`, `--flat-minutes`, and `--gap-seconds`. These flags are not
automatic exclusions or evidence of erroneous data. Long gaps break both plotted
lines and flat-stretch detection. Outputs at the selected output directory are replaced
on rerun; source histories, mappings and panels are never changed.

## 4. Construct descriptive responses and the reference posterior

```sh
uv run python main.py panel --events data/processed/events_2024.json \
  --history-dir data/interim/history_2024 --config configs/research.toml \
  --output outputs/panel_2024.json

uv run python main.py bayes --events data/processed/events_2024.json \
  --history-dir data/interim/history_2024 --baseline-time 2024-11-05T12:00:00Z \
  --max-age-seconds 120 --output outputs/posterior_2024.json
```

Choose the baseline before all known results, within the fetched history. The model
uses a single cycle/election type per run. Its common loading is assumed (default
1.0, change with `--loading`), not estimated. Results are a reference calculation
for checking the research design, not evidence of forecasting improvement.

Panel windows default to 5, 30, 60, 360 and 1440 minutes after the batch ends.
Pre-prices strictly precede the batch start. Post-prices are as-of the horizon and
must be after the last batch event. No interpolation, nearest-future matching, or
unlimited carrying of old quotes occurs. Every rejected response records a reason.

## Layout

```text
configs/                 study settings and empty curation templates
docs/                    methodology, contracts and implementation milestones
src/senate_market/
  ingestion/             Gamma catalog, CLOB samples, HTTP cache
  events/                reviewed mappings, calls and chronological batches
  features/              probability orientation and strict as-of alignment
  bayesian/              fixed-loading sequential reference model
  event_study/           response-panel construction and exclusion diagnostics
  evaluation/            proper scoring helpers
  cli.py                 public workflow
  demo.py                explicitly synthetic worked example
scripts/                 compatibility entry points for existing IDE tabs
tests/                   offline ingestion and inference correctness checks
data/raw/                created on use; cached response snapshots
data/interim/            created on use; catalog and history artifacts
data/processed/          created on use; reviewed event structures
outputs/                 created on use; panels and reference calculations
```

The full research phase can add notebooks and publication figures once coverage
and external event timestamps are validated. See the methodology for identification
assumptions, data-source boundaries, and the held-out evaluation plan.
