# 2024 race mapping review

`configs/races.csv` contains 34 reviewed party-outcome contracts from the local
`data/interim/catalog_2024.json`: 33 regular elections and Nebraska's special election.
`configs/races_2024_general.csv` contains only the 33 regular elections; use this
subset when building inputs for the current single-election-type Bayesian reference.
Do not mix the special election into that model's general-election inputs.

## Mapping decisions

- Each row selects the catalog's exact `Yes` token for a Democratic-win contract,
  with `orientation=identity`. Republican and other outcomes are not duplicated.
- Election date is November 5, 2024, as stated in each contract description.
- Regular races are Class 1, checked against the
  [Senate's Class I list](https://www.senate.gov/senators/Class_I.htm).
  Nebraska's special contract explicitly specifies Class 2, also checked against
  [Nebraska's Senate seat history](https://www.senate.gov/states/NE/senators.htm).
- Maine (500735) and Vermont (500731) explicitly include Angus King and Bernie
  Sanders respectively in the Democratic event. `party=Democratic` denotes the
  contract's definition, not a claim about either person's party registration.
- Nebraska regular (500686) has no corresponding independent-candidate exception.
  Its Democratic-win token must not be interpreted as any non-Republican winning.
- Nevada (500105) has a misleading Michigan market slug. Its question, description
  and parent event identify Nevada; the mapping uses its ID rather than that slug.
- California (500659) is mapped once to the regular election, following the
  contract's regular-election context. No separate special-election observation is
  inferred from this same contract.
- Candidate and optional covariates are blank: these are party contracts, and
  polling, incumbency and vote-margin data have not been sourced here.

Each row's source URL addresses the exact Gamma market ID. `reviewed=true` means
the race/token identity and contract direction were checked; it does not certify
complete price coverage or supply election results.

## Still required before empirical analysis

`configs/events.csv` now contains 31 sourced AP calls using these race IDs;
three remain pending. See [event review](event_review.md) for sources and limits.
Contract settlement requires agreement among AP, Fox and NBC
(or official certification); settlement time is not automatically the first call.
No race-call timestamp, result or `unresolved_through` cutoff is inferred from prices
or Gamma's closed flag. Optional covariates remain missing rather than fabricated.

All selected tokens should be checked against the coverage manifest before analysis;
an observed history alone does not establish usable coverage at every event window.
