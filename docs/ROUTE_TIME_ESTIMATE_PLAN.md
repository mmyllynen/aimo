# Route Time Estimate Plan

## Goal

Estimate how long a stored route or route-like workout would take for the current user. The estimate must be deterministic application logic: LLMs may route/extract a typed request, but Python owns data access, route feature extraction, model choice, validation, uncertainty, and user-facing facts.

The first user-facing result is prose:

- primary time estimate
- likely range
- confidence level
- short explanation of route factors and user-history basis

Later phases may render the estimate on route maps and split it by waypoints or distance bands.

## Inputs That Can Affect Time

Route geometry and elevation:

- distance
- ascent, descent, and net elevation change
- elevation range
- grade distribution
- sustained climbs and descents
- steep climb/descent share
- rolling up/down variation
- route-point density and gaps
- out-and-back or overlapping sections
- waypoint count and navigation complexity

User history:

- recent pace on comparable activities
- longer-term pace on comparable activities
- distance-specific pace
- ascent penalty observed from the user's workouts
- performance on similar ascent-per-km profiles
- trend over recent workouts
- elapsed vs moving-time behavior when available
- data volume and recency
- same route or same title history

Precomputed workout features:

- normalized distance, duration, pace, and moving/elapsed-time fields when available
- ascent, descent, elevation gain/loss density, and elevation range
- grade distribution buckets, such as flat, climb, steep climb, descent, and steep descent shares
- sustained climb/descent summaries, including longest climb, steepest sustained segment, and total climb time/distance proxies
- route shape signatures for same-route and out-and-back detection
- point quality indicators: point count, distance/elevation coverage, gaps, and smoothing quality
- comparable-workout keys: owner, activity kind, local date, distance band, ascent-per-km band, and route signature hash

Future external/contextual factors:

- sport/mode: run, hike, bike, walk
- route surface and technicality
- road/trail/path classification
- intersections, stops, gates, stairs, ferry/tunnel constraints
- weather, daylight, season, snow/ice
- target effort: easy, normal, race, social, with breaks
- load/fatigue from recent training

Weather/context:

- intended date and time of day
- route centroid/bounds from GPX-derived compact features
- forecast availability window and provider reliability
- heat/apparent temperature and humidity
- cold exposure
- wind speed and gusts
- precipitation probability and amount
- snowfall/ice proxy
- seasonal climatology fallback when forecast is unavailable

## Phase 1: Deterministic Text Estimate

Scope:

- Implement a deterministic estimate for one resolved stored route/workout.
- Trigger via formal tags such as `+estimate`, `+ennuste`, or `+aikaennuste`.
- Use the current workout reference resolver to select active/latest/specified workout.
- Use stored user workouts as history.
- Return plain text with metadata.
- Do not call the LLM for the final prose.

Data:

- Target route facts: distance, ascent, point/elevation availability, grade profile when points are available.
- User comparable workouts: same owner, completed activities with distance and duration.
- Exclude the target workout from history if it has duration, so route plans and completed activities can both be estimated.

Model:

- Baseline pace is the median pace of comparable user activities.
- Prefer activities with the same `primary_kind` when enough data exists.
- Route ascent penalty starts from the user's observed ascent penalty when enough variation exists; otherwise use a conservative fallback.
- Apply a simple distance adjustment from comparable workout distance.
- Produce a confidence level from history count, route data completeness, and route similarity.
- Produce a wider range when data is sparse or route features are missing.

Output:

- `Arvio tälle reitille: 2 h 35 min`
- `Todennäköinen vaihteluväli: 2 h 20 min - 2 h 55 min`
- route facts used
- history count and confidence
- missing data notes

## Phase 2: Better Route Features

Implemented baseline:

- Route-time-estimate feature records are computed during GPX ingest and stored in SQLite.
- A deterministic backfill service function can rebuild feature records for existing workouts.
- Stored feature records are compact derived data, not raw points: ascent/descent, grade distribution, sustained climb/descent summaries, route shape signature, route centroid/bounds, distance/elevation coverage, and quality flags.
- Feature calculation is deterministic and versioned so future model changes can distinguish feature schema versions.
- Estimation uses stored feature records when available and falls back to workout summaries/points when a feature record is absent.

Remaining refinements:

- Expose the backfill service through an explicit operator command or maintenance script.
- Detect out-and-back/overlap complexity as a navigation note from the stored route signature.
- Separate flat pace, climbing penalty, descending penalty, and fatigue adjustment in metadata.
- Add tests with synthetic routes.

Rationale:

- GPX ingest is the natural point where full point arrays are already parsed and validated.
- Persisting compact estimate features makes route-time estimates faster, easier to explain, and less dependent on repeated full-history scans.
- Feature records create a stable foundation for similarity search, weighted estimates, and residual-based uncertainty in later phases.
- The database should keep enough indexed fields to select comparable workouts by owner, kind, recency, distance band, ascent-per-km band, and route signature without loading detailed streams.

## Phase 3: Similarity-Based Estimation

Implemented baseline:

- Select and weight comparable workouts by distance, ascent per km, kind, recency, distance/ascent bands, route signature, and grade profile.
- Use weighted median pace instead of broad global median when feature records are available.
- Estimate likely range from weighted residuals on comparable workouts when enough data exists, with confidence-based fallback.
- Persist compact model/similarity metadata in workflow output and conversational LLM facts.
- Persist compact explanation facts for later "why this estimate?" conversational follow-up.

Remaining refinements:

- Detect "same route" candidates by title and route geometry similarity.
- Improve recency handling for route plans without target dates.
- Calibrate weights and residual ranges against more real user data.
- Add richer explanation text once the model metadata is stable.

## Phase 3b: Explainable Estimate Follow-Up

Implemented baseline:

- Natural-language explanation requests are interpreted through a typed intent.
- The workflow retrieves the latest route-time-estimate history metadata from the channel.
- The reply LLM receives only compact stored explanation facts, not raw GPX or point streams.
- Explanation facts include model, estimate/range, confidence, comparable count, effective sample size, baseline pace, ascent and distance adjustments, uncertainty source, and compact similarity score summaries.

Remaining refinements:

- Add a deterministic fallback explanation when the LLM is unavailable.
- Support explicit references to older estimates if multiple route estimates appear in the same channel.

## Phase 3c: Calibration And Backtesting

Goal:

- Measure whether the feature-similarity model is actually better than the earlier median-based estimate.
- Calibrate similarity weights and uncertainty ranges from the user's realized activity history instead of relying only on hand-tuned heuristics.

Method:

- Run leave-one-out validation over completed user activities.
- For each completed activity, treat it as the target route and estimate its duration from the remaining comparable activities.
- Compare estimated time against the actual stored duration.
- Record absolute error in minutes, percentage error, signed error, and whether the actual duration falls inside the predicted range.

Report:

- median absolute percentage error
- median absolute minute error
- bias: typical overestimate/underestimate
- interval coverage: how often the actual duration is inside the predicted range
- results by distance band and ascent-per-km band
- effective sample size distribution
- cases where the model has high confidence but large error

Use the report to:

- tune distance, ascent, grade, recency, and route-signature weights
- adjust distance and ascent penalties
- calibrate uncertainty ranges by observed residuals
- decide when confidence should be downgraded despite many available workouts
- expose stable user-facing quality facts such as "historically this model's typical error is about X%"

Constraints:

- Backtesting uses only owner-scoped stored workout summaries/features.
- Raw GPX and full point streams stay out of LLM inputs.
- Calibration should be deterministic and runnable as an operator/maintenance check.

## Phase 4: Route Map Integration

- Add optional route-map overlay with estimated total time.
- Add waypoint-to-waypoint estimated elapsed times.
- Add distance-band split estimates.
- Keep visualization deterministic and bounded.

## Phase 5: Contextual Modes

- Add explicit controls for `mode=moving|elapsed`, `effort=easy|normal|race`, and `activity=run|hike|bike|walk`.
- Add optional surface/OSM analysis when available.

Implemented weather baseline:

- Natural-language route-time intent can return `activity_intent`, `target_date`, and `target_time_of_day` through the typed LLM contract.
- Python validates the target date and uses the route centroid from compact estimate features, falling back to route points when needed.
- A configured Open-Meteo provider retrieves daily forecast facts for the route location/date.
- If live forecast is unavailable, disabled, or outside the forecast window, Python uses deterministic seasonal climatology and records the limitation.
- Running estimates are adjusted deterministically for heat/apparent temperature, cold, wind/gusts, precipitation, and snow/ice proxy.
- Conversational estimate and explanation replies receive only compact weather facts, base estimate, adjusted estimate, adjustment components, provider source, and limitations.

Remaining refinements:

- Add explicit deterministic controls for `activity=run|hike|bike|walk`, `effort=easy|normal|race`, and `mode=moving|elapsed`.
- Calibrate weather adjustment percentages from the user's historical workouts once enough weather-labeled completed activities exist.
- Use route direction and wind direction for headwind/tailwind weighting when route geometry support is mature enough.
- Add time-of-day weather selection if the provider and intent include reliable hourly data.
- Add seasonal daylight/snow/ice context for dates outside the forecast window.
- Add operator-visible metrics for forecast failures and climatology fallback frequency.

## Safety And Privacy

- Keep raw GPX and full point arrays out of LLM inputs.
- Keep estimates owner-scoped.
- State uncertainty explicitly.
- Never imply medical, safety, or race-readiness guarantees.
- Prefer "estimate" language over claims of exact prediction.
