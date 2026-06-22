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

---

## 4. (Optional) Grab the naive template — smoke test

```
GET /api/v1/forecasts/naive-template/{round_id}
```

Returns a ready-to-upload naive forecast (persistence = last context value). You can `POST` it directly to `/forecasts/upload` as an end-to-end smoke test to verify the full workflow before submitting a real forecast.

---

## 5. Upload your forecast

```
POST /api/v1/forecasts/upload
```

Send the following:

- `round_id`, `model_name`
- `forecasts`: one entry per series, each with its `challenge_series_name` and a list of `{ts, value, probabilistic_values?}` points.

**Important:**

- Use the `challenge_series_name` identifiers from the context data, **not** raw series IDs.
- Submit only within the registration window (`registration_start`–`registration_end`) and within the forecast horizon.

---

## Reviewing submissions

```
GET /api/v1/forecasts/{round_id}/{model_id}
```

Lets you review the forecasts you've submitted for a given round and model.

---

## Example implementation

For a complete, end-to-end reference covering model registration, context acquisition, and forecast upload, see the TS-Arena example implementation on GitHub:

[https://github.com/DAG-UPB/ts-arena/tree/main/ts-arena-participation_example](https://github.com/DAG-UPB/ts-arena/tree/main/ts-arena-participation_example)

TS-Arena is a live forecasting benchmark. The repository is the recommended starting point once your model is registered.

---

> **Placeholders:** replace `<OrgName>/<fancymodelname>` with your organization and model name throughout.
