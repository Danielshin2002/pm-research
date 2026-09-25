# 2024 AP call event review

`configs/events.csv` contains 31 sourced calls, including Nebraska's special
election. `configs/events_2024_general.csv` contains the 30 regular-election calls
and must be paired with `configs/races_2024_general.csv` for the reference model.
Three race times remain unverified and are listed in `configs/events_pending.csv`.
That pending file is an audit checklist, not an input to the events command.

## Definition and provenance

The event clock is the Associated Press call, not the earliest call across all
networks, a candidate concession, official certification or market settlement.
Sources are AP reports (including syndicated copies), except California, where
CalMatters reporting carried by CapRadio explicitly places the AP regular-election
call at poll closing. Each event includes the source URL and winning candidate.
No article publication timestamp was substituted for the call time.

All included times are minute precision. EST converts to UTC by adding five hours;
California's 8pm PST call converts to 04:00 UTC the next day. Seconds of `00`
are storage convention, not claimed second-level precision. Most calls dated
November 5 locally therefore appear on November 6 in this file.

Results encode the called winner against the reviewed contract definition:
1 for a Democratic win and 0 otherwise. Maine and Vermont count King and Sanders
as Democratic under their contracts. These are called binary outcomes, not a
dataset of certified vote totals. `realized_vote_margin` remains missing.
California's regular call is not its later special-election call. Pennsylvania
uses the initial AP call on November 7, not a later concession or recount date.

## Limits before interpretation

- Delaware, Hawaii and Utah have no included call time. They must remain
  unsequenced and be excluded as targets without a separately sourced status
  cutoff. Never interpret missing timestamps as proof a race was still open.
- Maine, Pennsylvania, Nevada and Arizona calls fall after the current history
  ends at November 7 00:00 UTC. Keep their calls for status tracking; do not treat
  missing post-call prices as zero change. A later call does not establish that
  the contract was tradable throughout the earlier period.
- AP may call later than other networks. The panel's known-result cutoff is only
  an AP-based proxy until earlier public calls and actual settlement times are
  audited. It does not guarantee genuinely unresolved markets.
- This file does not yet include presidential calls, concessions, other networks'
  calls, or other overlapping news. The contamination filter cannot catch news
  that has not been supplied. Use outputs for exploratory analysis, not causal
  claims about the effect of a single Senate result.
- Minute precision warrants timestamp-shift sensitivity checks for five-minute
  windows. Price coverage still needs validation around every event.

For more background, see [AP's call methodology](https://www.ap.org/elections/our-role-in-the-u-s-elections/how-we-declare-winners/).
