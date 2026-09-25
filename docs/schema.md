# Data contracts and relational design

The current pipeline uses CSV curation inputs and versioned JSON artifacts. This
document distinguishes implemented fields from planned enrichments. A future
DuckDB/Parquet implementation can use the following logical tables and keys.

| Table | Key | Important fields | Current representation |
|---|---|---|---|
| market | market_id | condition_id, question, slug, venue dates, closed, review_status | catalog.json → markets |
| outcome | token_id | market_id, label | catalog.json → markets → outcomes |
| race | race_id | cycle, state, senate_class, election_type, election_date | races.csv / events.json → races |
| race_outcome_mapping | race_id | market_id, token_id, outcome_label, orientation, reviewed, source_url | races.csv |
| observation | token_id, timestamp | probability, source, fidelity | history/TOKEN.json → points |
| information_event | event_id | race_id, event_type, timestamp, precision, result, source_url | events.csv / events.json → events |
| batch | batch_id within run | cycle, election_type, start, end, member events | events.json → batches |
| response | batch_id, target_race_id, window_minutes | source surprises, pre/post prices, delta_logit, overlaps | panel.json → responses |
| exclusion | batch_id, target_race_id, window_minutes | reason, overlapping_event_ids | panel.json → excluded |
| retrieval | record_sha256 | endpoint, parameters, retrieved_at, raw payload | data/raw/http/responses/*.json |
| posterior | model run, batch_id | theta weights, mean/SD, remaining-race predictions | posterior.json → trajectory |

## Market and observation rules

Gamma market ID, on-chain condition ID, and decimal outcome-token ID remain distinct
strings. Outcome order is preserved. Empty/missing token arrays mean a catalog
entry may have no accessible CLOB series. The text classifier marks candidates;
it never supplies the cycle, state, class, party or election result for analysis.

`created_at`, `start_date`, `end_date` and `gamma_closed_time` retain Gamma values.
They do not populate election-call or settlement fields automatically. Observations
use timezone-aware ISO-8601 UTC. The final price-history interval is `[start,end)`.
Samples must be finite and within [0,1]; conflicting prices at one token/timestamp
are errors. Missing price, volume, depth and margin values are never replaced by zero.

## Required reviewed race mapping

`race_id`, `cycle`, `senate_class`, `state` (two-letter U.S. code), `election_type`,
`election_date`, `market_id`, `token_id`, `outcome_label`, `orientation`, `source_url`,
and `reviewed=true`. One canonical token per race is supported in this phase.

Use race IDs that distinguish regular and special elections, e.g.
`2024-NE-class1-general` versus another Nebraska seat. Do not use state alone as
the persistent research key. Optional candidate, party and incumbency fields are
reviewed annotations. Class is metadata, never the temporal ordering variable.

`orientation=identity` represents Democratic-win probability as the chosen token's
price. `complement` represents it as one minus that price; the reviewer must verify
logical equivalence for the contract. Do not aggregate overlapping candidate markets
or assume a third-party outcome has zero probability. `unresolved_through`, when
provided, is a sourced UTC time asserting no known result through that time; it is
needed for target eligibility if no call/settlement time is available.

## Event input

Required: `event_id`, `event_type`, `timestamp`, `time_precision`, `source_url`.
`race_id` is required except for general `other_news`. Types: `poll_close`,
`first_returns`, `race_call`, `market_resolution`, `other_news`. Precision: `second`
or `minute`; retain uncertainty in notes and test batching/window sensitivity.

Calls and settlements additionally require a verified binary `result` under the
study's party definition. `result=1` is Democratic win; `0` is not a Democratic win.
First returns and poll closes must not carry the eventual result. Conflicting or
multiple calls of the same race/type must be adjudicated outside the estimator.
Retain retraction/verification details in notes before selecting an accepted call.

`realized_vote_margin` is optional annotation, not a prediction-time feature.
Record whether a margin is partial/unofficial/certified and its publication time
before using it in any later extension. The event builder preserves annotation columns.

## Proposed enrichment tables (not yet populated)

- `race_covariate(race_id, available_at, source_url, variable, value)`: expected
  margin, polling average, partisan lean, incumbency and demographic data. Keep
  versioned values and units; margins should declare percentage points versus shares.
- `race_result(race_id, published_at, result, vote_margin, status, source_url)`:
  independent official labels, including revisions and certification status.
- `pair_similarity(source_race_id, target_race_id, trained_through, definition,
  value)`: regional, demographic, voting and polling-error similarities learned
  using training data only.
- `book_observation(token_id, timestamp, source, bid, ask, spread, depth, quality)`:
  optional Pendulum source; no Gamma snapshot backfill into historical rows.
- `forecast(race_id, forecast_time, model_version, probability, training_cutoff)`:
  future held-out predictions, with outcome labels joined only for scoring.

The analysis view joins observations → outcome mapping → race to obtain
`timestamp × market_id × state × cycle × senate_class`. Event-response views are
keyed by batch/target/horizon. Batch IDs are run-local: never join them across
configurations without including run identity and event membership.

## Reproducibility and missingness

Each catalog/history output records requests and retrieval times. Exact HTTP
requests have a replay cache; immutable response snapshots are addressed by a hash
of the canonical JSON envelope, including retrieval time. Refresh changes the replay
pointer while preserving previously referenced responses. This is a content hash
of the stored JSON representation, not a claim to hash original transport bytes.

Save different study windows/configurations to different normalized-output paths.
Panel and posterior outputs record input paths, SHA-256 hashes and settings.
Archive the complete input artifacts with the run; hashes detect changes but do
not preserve the old contents of files. History loaders check file hashes against
coverage manifests when hashes are present.
Failed fetches are recorded in coverage manifests; analysis loaders will not use
stale files for those tokens. Hand-supplied histories without a manifest are allowed
for synthetic/offline tests and require provenance review for empirical work.
