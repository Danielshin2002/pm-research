# Bayesian sequential analysis of U.S. Senate prediction markets

## Scope and decision

This implements the first research phase of the supplied
`senate_prediction_market_bayesian_analysis.md`: a reviewable methodology,
data contracts, ingestion pipeline and reference calculations. The empirical
question is whether newly public state-race information predicts changes in
unresolved Senate probabilities, and whether an explicit Bayesian update improves
forecasts relative to available market probabilities.

Use Gamma for historical and current listings, and Polymarket's price-history
service for each outcome token. Neither service's availability proves complete
election-cycle coverage. Earlier discussion of guaranteed 2024 or older probability
history should be treated as unverified until the actual tokens pass a coverage audit.

Start with 2024 only if the audit supports it. Collect a prospective 2026 panel
using the same preregistered rules. Those cycles contain different Senate classes;
they are not a matched same-seat sample. Match state, class and regular/special
seat only for cycles six years apart when comparable data actually exist.

## Statistical architecture

The unit for price responses is **information batch × unresolved target race ×
window**, with source surprises retained individually within a batch. This avoids
duplicating a target price change as though each simultaneous source event were
an independent outcome. The outcome-forecast unit is race × prespecified decision
time, not every source/target pair.

1. Inventory candidate markets, including closed listings, without selecting on
   eventual winners or final volume.
2. Curate one canonical outcome token per race and a consistent party definition.
3. Audit observable price support in each required period.
4. Curate timestamped calls, results and overlapping information separately.
5. Build within-cycle chronological batches and strict as-of price comparisons.
6. Run the reference model and diagnostics.
7. Fit richer models and evaluate only after independent event and covariate data
   have been assembled and coverage limitations documented.

Dependencies currently stay small: requests plus standard-library JSON/CSV/TOML.
The relational design in `schema.md` can later be materialized as Parquet/DuckDB
without changing scientific keys. Raw payloads and retrieval times are retained.

## Data boundaries and coverage audit

Gamma market IDs, condition IDs and outcome-token IDs are different identifiers.
Normalize JSON-encoded outcome/token arrays by their shared index; reject mismatched
arrays. Keep IDs as strings. Older listings without usable tokens stay in the
catalog rather than disappearing from the sample denominator.

Gamma metadata timestamps are venue timestamps. `endDate` is not a verified election
date; `closedTime` is not a race-call time or a guaranteed final settlement time.
Current prices, volume and liquidity cannot be used as historical covariates.

Price acquisition uses explicit UTC start/end bounds and minute fidelity. Each
query is chunked, samples are sorted, duplicate boundaries are reconciled, and the
right endpoint is excluded. The coverage report distinguishes observed data, empty
responses and errors. It reports first/last times, maximum/median gaps, edge gaps
and empty chunks. These are descriptive audit measures, not a completeness certificate.

Reconcile the candidate catalog with an external list of actual U.S. Senate races.
Audit 2022, 2024 and 2026 separately, including uncontested and illiquid races.
Report matched races, available tokens, usable calls, exclusions and retained targets.
A Senate text filter is not exhaustive or specific enough to define the universe.
No claim about long history follows merely from an old Gamma creation date.

## Outcome definition and feature timestamps

The starting general-election outcome is `Y=1` for a Democratic win. An independent
who caucuses with Democrats requires a documented alternative definition applied
consistently to prices and outcomes. Do not silently assign party from `Yes`/`No`.
Complementing a Republican-win token equals Democratic-win probability only if
those are exhaustive alternatives for the defined contract. Distinct candidate
contracts can overlap or leave residual outcomes; review them individually.

Analyze primaries separately: “Democratic win” is not the same estimand in an
intraparty contest. The pipeline carries election type, but primary model estimation
requires a different, explicit outcome definition. General and special elections
are also kept in separate baseline runs; pooling is a later modeled choice.

Every covariate used for prediction needs a publication/availability timestamp.
Examples: polling snapshot, expected margin, incumbency, partisan lean, demographic
features, and historical polling-error correlation. Realized certified margin is
an evaluation label; it cannot enter an election-night forecast until public.
The current templates store optional values but the prototype does not estimate
their effects or assume they were available at the event time.

## Event construction

An election takes place on a date; information arrives over time. Keep separate:
poll close, first returns, major vote dumps, a reporting organization's race call,
and contract settlement. First returns may precede a call by hours but do not reveal
the eventual binary result. The first implementation uses documented race calls
as comparable result events and other observations as overlapping-information flags.

Calls may confirm information already priced in. Report anticipatory movements
and pre-trends. A price crossing 0.95 is a useful diagnostic, but not an exogenous
news event: defining a treatment by the price itself creates selection bias.
Analyzing vote-return shocks would require timestamped reported margins plus a
model of remaining ballots; that is a distinct extension.

Default selection: documented call; settlement only with explicit fallback enabled.
There is no binary-result update at poll close or an invented midnight timestamp.
Require timezone-aware timestamps and second/minute precision. Record the call
provider and source URL. Conflicting/retracted calls require adjudication before
they enter a Bernoulli update. Date-only records remain outside intraday analysis.

Within each cycle/election type, sort actual times and start a batch at the earliest
unassigned call. Include calls within five minutes of that first call. Do not extend
the interval through a chain of adjacent calls. Repeat with 1- and 10-minute batching.
No state or Senate-class order is hard-coded. One race result enters the model once.

## Surprise and descriptive event study

For source race i in batch b, use the last sufficiently fresh price strictly before
the batch begins: `s_i = Y_i - p_i(t_b-)`. All source prices in a batch share this
information boundary. Raw surprise is the initial descriptive measure. Standardized
Bernoulli errors require probability clipping and are unstable near 0/1; margin
surprise requires independently timestamped expected and observed margin data.
Do not apply logit to a binary result.

For target j, define the response at delta minutes after the final call in the batch:

`D_jb(delta) = logit(p_j(t_b_end + delta)) - logit(p_j(t_b_start-))`.

Use 5, 30, 60, 360 and 1440 minute windows. Prices are selected backward as-of,
never using a future observation to populate an earlier timestamp. Both source and
target prices have a configurable maximum age; the default is 120 seconds. The
post sample must follow the last batch call. Exclude target races already called
by the horizon, or with unverified unresolved status. Clip prices to `[1e-6,1-1e-6]`
only for numerical logit evaluation, retaining unmodified prices in the output.

Requested history fidelity must not exceed the response window. That is only a
minimum check: timestamp semantics, actual gaps and event-time uncertainty still
need review. A sampled price series cannot establish tick-level reactions.

Flag other calls, returns, settlement events or manually curated news between five
minutes before the batch and the end of the response window. Default analysis
excludes these windows; a sensitivity run retains flagged responses. This conservative
rule does not eliminate unobserved common news. Long windows will often be crowded.

The proposed regression for isolated singleton batches follows the supplied brief:

`D_ji = b1*s_i + b2*similarity_ij + b3*s_i*similarity_ij + controls_ij + error_ji`.

For multi-source batches use source-specific predictors or a prespecified weighted
sum `sum_i w_ij*s_i` with weights learned/fixed outside the test period. Do not expand
a batch into duplicated dependent responses and treat them as independent. Include
target baseline odds and time controls; add historical liquidity only if available.
Use dependence-aware uncertainty by source batch and target race. With very few
clusters, asymptotic clustered standard errors are unreliable; report sensitivity
using batch/block resampling and a small-sample method. Regression fitting is deferred.

## Bayesian specification and implemented reference model

Freeze all market probabilities at a common time t0 before the first observed result.
Within one cycle/type define:

`theta ~ Normal(0,1)`

`q_i(theta) = logistic(a_i + beta_i*theta)`

`Y_i | theta ~ Bernoulli(q_i(theta))`.

Fix the scale and sign of theta; otherwise beta and theta are not identified.
The reference implementation fixes all beta_i to a common positive loading (default
1) and evaluates 401 grid points on [-6,6]. It calibrates each a_i numerically so
`E_prior[q_i(theta)] = p_i(t0)` (after disclosed endpoint clipping). Simply setting
`a_i=logit(p_i(t0))` would generally fail this marginal calibration under a nonzero
latent-factor variance.

For a batch B, update once with the joint conditional likelihood:

`w_new(theta) proportional to w_old(theta) * product_i_in_B P(Y_i | theta)`.

Integrate posterior predictions over theta; do not plug the posterior mean into
the nonlinear logistic function. Output the prior grid, frozen anchors, weights,
posterior mean/SD and remaining-race predictions after each batch. Results become
available at the batch end. Within-batch order cannot change the posterior.
Never re-anchor to live market odds and then apply the same results again.

This model shows the mechanism; it does not estimate race sensitivity or demonstrate
that the mechanism is true. Sensitivity runs should vary the common loading and grid
range/resolution, especially where posterior mass approaches grid edges. The static
factor and conditional independence assumptions are substantive restrictions.

For the fitted extension, use a baseline adjustment `u_i ~ Normal(0,sigma_u)` around
calibrated a_i, with a regularizing half-normal prior on sigma_u. A positive loading
could have `log(beta_i) ~ Normal(z_i*gamma,sigma_beta)` with centered/scaled predictors,
regularized gamma and a half-normal sigma_beta. Fix the factor prior scale. Regional
effects require their own identified scales and pooling. Use historical training
cycles or external priors: one binary outcome per race in one cycle cannot support
unrestricted race intercepts and sensitivities. Check prior predictive realism,
simulation recovery, posterior predictive fit, convergence and effective sample sizes.

A dynamic theta_t requires an explicit transition model and time-gap-dependent
process variance. It is not obtained by reusing a static prior across different
election years. Partial returns require a margin/count likelihood, not an early
observation of the eventual winner.

## Identification and validation

Race-call order is endogenous: competitive or slow-counting states are called later.
Unresolved markets, presidential prices and control markets can respond together
to county returns, exits, news and model updates. Temporal association is not causal
transmission. Narrow windows, batching, pre-trends, placebo times and excluded crowded
windows diagnose problems but do not prove causality.

National market movements can be useful comparison outcomes. Contemporaneous
movements may themselves be mediators; report specifications with and without those
controls rather than interpreting all such controls as harmless confounder removal.

Before forecasting tests, freeze the outcome definition, t0, horizons, exclusions,
feature sources, tuning procedure and clustering. Use chronological held-out cycles
where possible, or preregister a prospective cycle. Never randomly split duplicated
event-target rows across training/test. Similarity features and hyperparameters must
be estimated only on earlier data. The six-year same-class comparison is optional
and gated on actual historical availability.

Compare frozen baseline markets, contemporaneous markets at the forecast time,
the sequential Bayesian reference, polling-only, and combined models. The comparison
to contemporaneous markets is essential: election results may already be incorporated.
Score identical races at identical decision times with Brier score and log loss;
inspect calibration and coverage. Aggregate repeated predictions by prespecified
time/race weights. Accuracy and AUC are secondary and may be uninformative with few
unresolved competitive races. `evaluation.scores` provides proper-score arithmetic;
there is no implemented held-out experiment or reported performance advantage yet.

## Milestones and outputs

1. **Implemented:** Gamma/CLOB ingestion, coverage reports, reviewed event contracts,
   anchored batches, descriptive panel, fixed-loading grid reference, synthetic demo.
2. **Data gate:** verify historical race universe, usable prices, sourced calls and
   timestamped external covariates. If 2024 fails, narrow scope or add another source.
3. **Empirical pilot:** diagnostics, prior/posterior figures, individual-source
   contributions, window comparisons, and observed state-to-state heatmaps labeled
   as associations. Multi-source attribution needs a declared rule, not arbitrary order.
4. **Fitted research:** hierarchical inference, dependence-aware regression, calibration
   and held-out comparisons. Produce figures and tables with sample/exclusion counts.

## Source documentation

- [Gamma keyset markets](https://docs.polymarket.com/api-reference/markets/list-markets-keyset-pagination):
  cursor pagination, closed-state filtering, date filters and token metadata.
- [Polymarket price history](https://docs.polymarket.com/api-reference/markets/get-prices-history):
  token identifier, timestamp bounds and minute fidelity.
- [Polymarket research data guide](https://institute.polymarket.com/data):
  separation of metadata and price-series services.

Record endpoint behavior and coverage from actual retrievals; documentation alone
does not establish retrospective availability or event-time sampling quality.
