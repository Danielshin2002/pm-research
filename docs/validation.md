# Implementation validation

The unit tests and synthetic example run offline. They cover Gamma JSON-string
array normalization, open/closed pagination, repeated pages, server-imposed page
caps, chunk boundary deduplication, empty/error history, UTC requirements, reviewed
token mapping, event batching, call/settlement separation, stale and future prices,
overlap exclusions, missing target status, fixed-prior inference, proper scores and
the CLI demonstration.

Initial implementation validation passed: 29 tests, Ruff lint and formatting, lockfile consistency,
the direct-script workflow, the installed `senate-market` entry point, and cached
replay of the live history probe. On this macOS workspace, the generated editable
installation `.pth` file had its filesystem `hidden` flag set, causing Python to
skip it. Clearing that flag on
`.venv/lib/python3.12/site-packages/_editable_impl_pm_research.pth` restored the
installed entry point. The direct `python main.py` workflow also works independently
of editable-install path processing.

Live read-only checks during implementation produced:

- Gamma `/markets` returned a listing created in 2020. This establishes catalog
  reach for that listing, not usable probability history.
- A request for 500 markets returned 100. The initial offset implementation advanced
  by returned row count and stopped on an empty page. A three-page
  2024 closed-market scan read 300 listings and identified five Senate candidates;
  it correctly remains partial. Those candidates include control/primary contracts,
  so they are not an approved state-general-election sample.
- The Democratic outcome of **Senate control after 2024 election?**, Gamma market
  `252298`, returned 2,874 price samples over `[2024-11-05T00:00:00Z,
  2024-11-07T00:00:00Z)` at requested one-minute fidelity. Its token ID is
  `106428415972306440805659798821565836957352710901932544423124141186478841559835`.
  First sample: `2024-11-05T00:00:02Z`; last: `2024-11-06T23:59:02Z`.
  Median spacing was 60 seconds; the largest gap was 438 seconds. Fine fidelity
  does not imply continuous observations even in this successful example.

The local artifacts are under `data/interim/smoke/`, with request provenance and
raw cache references. They are gitignored. These observations verify API integration
and a particular historical series, not the availability of the complete Senate
race universe, 2022 price histories, external call timestamps or model performance.

Reproduce the historical probe:

```sh
uv run python main.py history \
  --token-id 106428415972306440805659798821565836957352710901932544423124141186478841559835 \
  --start 2024-11-05T00:00:00Z --end 2024-11-07T00:00:00Z \
  --fidelity 1 --chunk-days 1 --output-dir data/interim/smoke/history_2024
```

Use `--offline` to reproduce the exact cached responses or `--refresh` to check
current endpoint behavior. See the [official Gamma](https://docs.polymarket.com/api-reference/markets/list-markets)
and [price-history](https://docs.polymarket.com/api-reference/markets/get-prices-history)
documentation for endpoint contracts.

## Deep pagination correction

The initial bounded live checks did not reach Gamma's offset limit. A later full
2024 scan failed at offset 2100 with HTTP 422 and the response
`offset too large, use /markets/keyset for deeper pagination`.

Discovery now starts at `/markets/keyset` and forwards each `next_cursor` as the
next request's `after_cursor`, retaining all filters. It never sends `offset`.
Missing/empty next cursors terminate the scan, even on full pages; a short page
with a cursor continues. Repeated/non-advancing cursors and malformed envelopes
fail explicitly. Page size is validated against the documented maximum of 100.
Old offset-response caches remain intact; cursor requests have distinct cache keys.
HTTP failures now include the server's response detail.

The correction passes 39 offline tests and Ruff lint/formatting. Regression cases cover cursor
propagation/reset, short and full final pages, loops, malformed responses, and filter
preservation over more than 21 pages, and HTTP error details. The full live 2024 cursor
scan completed: 14,174 closed markets over 142 pages, plus two open markets on one
page. Both partitions were exhausted. It saved 186 Senate candidates to
`data/interim/catalog_2024.json`; these still require race classification and review.
See [Gamma's cursor contract](https://docs.polymarket.com/api-reference/markets/list-markets-keyset-pagination).
