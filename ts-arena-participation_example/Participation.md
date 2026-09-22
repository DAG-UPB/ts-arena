# TS-Arena API — Participation Workflow

- **Base URL:** [https://api.ts-arena.live/](https://api.ts-arena.live/)
- **Interactive docs:** [https://api.ts-arena.live/docs](https://api.ts-arena.live/docs)
- **Authentication:** every request is authenticated via the `X-API-Key` header using your personal API key.

> **Overall flow:** register a model → find an open round → fetch context → (optionally grab the naive template) → upload your forecast.
> Scoring is done via **MASE**, and ranking via **ELO**.

---

## 1. Register your model (required first step)

```
POST /api/v1/models/register
```

You need a registered model before you can participate in any challenge. Send the model metadata: `name`, `model_type`, `model_family`, `model_size`, `hosting` (use `"external"` as an external participant), `architecture`, `pretraining_data`, and `publishing_date`.

> **Note on `model_size`:** number of parameters in millions, or `null` if the model is rule-based.

The response includes your model's numeric **`id`**. Keep it — it is what the readback
endpoint in "Reviewing submissions" below takes. You can always look it up again with
`GET /api/v1/models/`, which lists your own models.

Example payload:

```json
{
  "name": "<OrgName>/<fancymodelname>",
  "model_type": "TSFM",
  "model_family": "e.g. Chronos",
  "model_size": 30,
  "hosting": "external",
  "architecture": "encoder-only",
  "pretraining_data": "synthetic, Gift-Eval Pretrain, Chronos Pretrain, ...",
  "publishing_date": "2026-04-15"
}
```

---

## 2. Find open challenge rounds

```
GET /api/v1/challenge/rounds
```

Returns rounds open for registration by default (filterable via `status` and `definition_id`).

To understand a challenge type, use:

```
GET /api/v1/challenge/definitions
GET /api/v1/challenge/definitions/{definition_id}
```

These describe the domain, frequency, horizon, and context length.

---

## 3. Acquire context data

```
GET /api/v1/challenge/rounds/{round_id}/context-data
```

Returns the historical context, grouped by anonymized `challenge_series_name`. Each group includes its `frequency` and a list of `(ts, value)` pairs.

### A round can be open before its context data is ready

A round appears in `GET /challenge/rounds` as soon as registration opens, which can be
**before** its context data is published. An empty response here is normal and temporary —
it does not mean the round is closed or that you are not eligible.

If your client polls, make sure it distinguishes *"I submitted"* from *"there was nothing to
submit yet"*. A poller that treats every pass over a round as final will retire the round on
its first look, and never forecast it — the round stays open, your submission never happens,
and nothing in your logs says so. Retry until you have uploaded, bounded by the round's
`registration_end`.

Track this **per model**, not per round. A retry after a partly successful upload must skip
the models that already landed: a duplicate upload is ignored by the platform and comes back
as `points_inserted: 0`, which a client that verifies its uploads will correctly read as a
failure — and then retry forever.

---

## 4. (Optional) Grab the naive template — smoke test

```
GET /api/v1/forecasts/naive-template/{round_id}
```

Returns a ready-to-upload naive forecast (persistence = last context value), including a
full set of quantiles. You can `POST` it directly to `/forecasts/upload` as an end-to-end
smoke test before submitting a real forecast.

It is also the cheapest way to see the exact timestamps and key format the platform expects
for a given round — diff your own payload against it when an upload is rejected.

---

## 5. Upload your forecast

```
POST /api/v1/forecasts/upload
```

Send the following:

- `round_id`, `model_name`
- `forecasts`: one entry per series, each with its `challenge_series_name` and a list of `{ts, value, probabilistic_values?}` points.

There is **no `user_id` field** — the request body has exactly the three keys above. Your
identity comes from the `X-API-Key` header, and the model is resolved from `model_name`
within your own models. Any extra key you send is ignored.

### Timestamps

Each series is anchored on **its own** last context point, not on the round's start time:

```
first forecast ts = (that series' last context ts) + frequency
```

and then one point per `frequency` step, `horizon / frequency` points in total.

There is **no round-wide "the forecast starts here" instant**, and `start_time` on the round
object is not one — it is informative only. The sources we ingest from are live, but not
real-time to the second: each publishes with a small lag. Usually that lag is harmless and
every series in a round sits at the same edge — but not always, and being one step off
invalidates every timestamp you submit. On some challenges the majority of series sit one or
more steps behind the round-wide value, and a round-wide anchor puts those on timestamps that
do not exist for them.

Take the anchor per series from the context data you fetched in step 3, and parse the
timestamps before comparing them — a plain string `max()` over ISO timestamps picks the wrong
one as soon as offsets or sub-second precision differ.

### Quantiles

`probabilistic_values` is a map of quantile level to value. Use the canonical keys:

```json
{"q_0.1": 41.2, "q_0.2": 43.0, "q_0.3": 44.1, "q_0.4": 45.0, "q_0.5": 45.8,
 "q_0.6": 46.6, "q_0.7": 47.5, "q_0.8": 48.9, "q_0.9": 51.3}
```

Bare `"0.1"` … `"0.9"` are accepted too and canonicalised on arrival. **Anything else is
silently dropped from that point** — `"0.10"`, `"p10"`, `"q10"`, `"median"` all fail this
way. Quantiles that cross are sorted ascending on arrival and reported back as a warning.

Probabilistic submissions are scored separately with the scaled quantile loss (SQL) and have
their own leaderboard. A point-only forecast is ranked on MASE alone.

**Important:**

- Use the `challenge_series_name` identifiers from the context data, **not** raw series IDs.
- Submit only within the registration window (`registration_start`–`registration_end`) and within the forecast horizon.

### Read the response — a 201 does not mean everything was stored

The upload endpoint accepts partial submissions. If one series is rejected and fifteen are
accepted, you still get **HTTP 201** with `success: true`. Checking the status code is not
enough:

```json
{
  "success": true,
  "message": "Successfully inserted 1440 forecasts (1440 with quantiles) with 1 error(s)",
  "forecasts_inserted": 1440,
  "model_id": 12,
  "points_inserted": 1440,
  "probabilistic_points_inserted": 1440,
  "errors": ["Unknown challenge_series_name 'zone_c' for round 12503"],
  "warnings": []
}
```

- **`points_inserted`** — compare it with the number of points you sent. Anything less means
  part of your submission did not land.
- **`probabilistic_points_inserted`** — how many of those carried usable quantiles. If you
  submitted quantiles and this is `0`, your keys were dropped.
- **`errors`** — conditions that cost you data. Treat any of these as a failed upload.
- **`warnings`** — advisories that cost you nothing (repaired crossings, unrecognised keys on
  an otherwise-accepted point). For backward compatibility these also appear in `errors`, so
  the fatal subset is `set(errors) - set(warnings)`.
- **`model_id`** — the numeric id this upload was attributed to, ready for the readback below.

Re-uploading the same round is safe: duplicates are ignored, so a repeat returns
`points_inserted: 0`.

---

## Reviewing submissions

```
GET /api/v1/forecasts/{round_id}/{model_id}
```

Returns what we actually stored — including `probabilistic_values` — so you can confirm your
quantiles persisted. `model_id` is the numeric id from your model registration, from
`GET /api/v1/models/`, or from the `model_id` field of the upload response above. You can
only read back your own models.

---

## Example implementation

For a complete, end-to-end reference covering model registration, context acquisition, and forecast upload, see the TS-Arena example implementation on GitHub:

[https://github.com/DAG-UPB/ts-arena/tree/main/ts-arena-participation_example](https://github.com/DAG-UPB/ts-arena/tree/main/ts-arena-participation_example)

TS-Arena is a live forecasting benchmark. The repository is the recommended starting point once your model is registered.

---

> **Placeholders:** replace `<OrgName>/<fancymodelname>` with your organization and model name throughout.
