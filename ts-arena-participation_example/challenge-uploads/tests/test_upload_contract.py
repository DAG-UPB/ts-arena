"""Contract tests for the reference uploader.

Run after changing anything under `challenge-uploads/src/` or `model-services/`:

    pytest challenge-uploads/tests/

They cover the two ways a forecast can be silently wrong on the wire:

* **Timestamps** (ts-arena #20) — each series must be anchored on its own last context
  point, parsed rather than string-compared, and the client must never guess a spacing it
  was not taught.
* **The upload response** (ts-arena #21) — a partially-rejected upload comes back as HTTP
  201 with `success: true`. The client must read the body and fail on it, rather than
  logging a tick based on what it sent.
"""
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name, relpath):
    spec = importlib.util.spec_from_file_location(name, ROOT / relpath)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


m = _load("uploader", "challenge-uploads/src/main.py")
naive = _load("naive_model", "model-services/example_naive/app/model.py")

FREQ = timedelta(hours=1)
BASE = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)
UTC_10 = datetime(2026, 9, 22, 10, tzinfo=timezone.utc)


class Resp:
    """Minimal stand-in for a requests.Response."""

    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


def _ctx(points):
    return [{"challenge_series_name": "s", "data": points}]


def _accepted(**overrides):
    body = {
        "success": True, "message": "ok", "forecasts_inserted": 10,
        "points_inserted": 10, "probabilistic_points_inserted": 10,
        "model_id": 12, "errors": [], "warnings": [],
    }
    body.update(overrides)
    return body


SENT = [{"challenge_series_name": "s", "forecasts": [{"ts": "t", "value": 1.0}] * 10}]


# --- timestamps: parse before comparing (ts-arena #20) -----------------------

@pytest.mark.parametrize(
    "points, string_max_picks, true_max",
    [
        pytest.param(
            [{"ts": "2026-09-22T10:00:00+00:00", "value": 1.0},
             {"ts": "2026-09-22T11:00:00+02:00", "value": 2.0}],
            "2026-09-22T11:00:00+02:00", UTC_10,
            id="non-utc-offset-sorts-later-but-is-earlier",
        ),
        pytest.param(
            [{"ts": "2026-09-22T10:00:00Z", "value": 1.0},
             {"ts": "2026-09-22T10:00:00.500000Z", "value": 2.0}],
            "2026-09-22T10:00:00Z",
            datetime(2026, 9, 22, 10, 0, 0, 500000, tzinfo=timezone.utc),
            id="subsecond-precision-sorts-earlier-but-is-later",
        ),
    ],
)
def test_anchor_is_the_parsed_max_not_the_string_max(points, string_max_picks, true_max):
    # the bug being guarded against: a lexicographic max over raw ISO strings
    assert max(p["ts"] for p in points) == string_max_picks
    _, _, max_timestamps = m.extract_history_from_context(_ctx(points))
    assert max_timestamps[0] == true_max


def test_mixed_offset_forms_still_resolve():
    _, _, max_timestamps = m.extract_history_from_context(_ctx([
        {"ts": "2026-09-22T09:00:00+00:00", "value": 1.0},
        {"ts": "2026-09-22T10:00:00Z", "value": 2.0},
        {"ts": "2026-09-22T08:00:00+00:00", "value": 3.0},
    ]))
    assert max_timestamps[0] == UTC_10


# --- timestamps: the client owns them, not the model service -----------------

def test_model_service_timestamps_are_overwritten():
    """Context arriving in a different order must not shift the forecast."""
    shuffled = [[{"ts": "WRONG-3", "value": 30.0},
                 {"ts": "WRONG-1", "value": 10.0},
                 {"ts": "WRONG-2", "value": 20.0}]]
    out = m.format_forecasts(shuffled, ["s"], [BASE], FREQ, 3)

    assert [p["ts"] for p in out[0]["forecasts"]] == [
        (BASE + k * FREQ).isoformat() for k in (1, 2, 3)
    ]
    # values are passed through untouched — only the timestamps are the client's business
    assert [p["value"] for p in out[0]["forecasts"]] == [30.0, 10.0, 20.0]


def test_each_series_anchors_on_its_own_context_edge():
    """Series lag. A round-wide anchor puts a lagging series on timestamps that do not
    exist for it, which the platform rejects per series."""
    out = m.format_forecasts(
        [[{"ts": "x", "value": 1.0}] * 2, [{"ts": "x", "value": 9.0}] * 2],
        ["on_time", "lagging"], [BASE, BASE - 6 * FREQ], FREQ, 2,
    )
    assert [p["ts"] for p in out[1]["forecasts"]] == [
        (BASE - 5 * FREQ).isoformat(), (BASE - 4 * FREQ).isoformat(),
    ]


def test_wrong_point_count_is_refused_before_upload():
    with pytest.raises(ValueError, match="expects 3"):
        m.format_forecasts([[{"ts": "x", "value": 1.0}]], ["s"], [BASE], FREQ, 3)


# --- frequency: no silent hourly fallback (ts-arena #20) ---------------------

def test_known_frequency_parses():
    assert m.parse_frequency("PT15M") == timedelta(minutes=15)


@pytest.mark.parametrize("bad", ["PT5S_bogus", "every other tuesday"])
def test_unknown_frequency_raises_instead_of_guessing_hourly(bad):
    with pytest.raises(ValueError):
        m.parse_frequency(bad)


# --- the upload response is read (ts-arena #21) ------------------------------

def test_fully_accepted_upload_returns_the_parsed_body(monkeypatch):
    monkeypatch.setattr(m, "http_post", lambda path, json_data: Resp(_accepted()))
    assert m.upload_forecasts(1, "M", SENT)["model_id"] == 12


def test_partially_rejected_201_raises(monkeypatch):
    """The exact shape the reporting participant hit: 201, success=true, most of it gone."""
    monkeypatch.setattr(m, "http_post", lambda path, json_data: Resp(_accepted(
        points_inserted=1, forecasts_inserted=1, probabilistic_points_inserted=0,
        errors=["Unknown challenge_series_name 'typo' for round 1"],
    )))
    with pytest.raises(m.UploadRejected, match=r"1/10 points"):
        m.upload_forecasts(1, "M", SENT)


def test_short_insert_without_errors_still_raises(monkeypatch):
    """Fewer points stored than sent is a failure even if the API listed no error."""
    monkeypatch.setattr(m, "http_post", lambda path, json_data: Resp(
        _accepted(points_inserted=7, forecasts_inserted=7)))
    with pytest.raises(m.UploadRejected, match=r"7/10 points"):
        m.upload_forecasts(1, "M", SENT)


def test_advisories_alone_do_not_fail_the_upload(monkeypatch):
    advisory = "Series 's': repaired quantile crossings on 2 forecast point(s)"
    monkeypatch.setattr(m, "http_post", lambda path, json_data: Resp(
        _accepted(errors=[advisory], warnings=[advisory])))
    assert m.upload_forecasts(1, "M", SENT)["model_id"] == 12


def test_works_against_an_api_portal_without_the_new_fields(monkeypatch):
    """`warnings` / `points_inserted` / `model_id` are backend-94 additions."""
    monkeypatch.setattr(m, "http_post", lambda path, json_data: Resp(
        {"success": True, "message": "ok", "forecasts_inserted": 10, "errors": []}))
    assert m.upload_forecasts(1, "M", SENT) is not None


# --- the example model's quantiles (ts-arena #21) ----------------------------

SERIES = [1.0, 4.0, 2.0, 9.0, 3.0, 7.0]
CANONICAL = {f"q_0.{i}" for i in range(1, 10)}


def test_quantile_keys_are_canonical():
    """`"0.10"`, `"p10"` and `"q10"` are all silently dropped by the API. `q_0.1` is not."""
    assert set(naive.NaiveForecastModel()._compute_quantiles(SERIES, 5.0)) == CANONICAL


def test_quantiles_are_deterministic():
    model = naive.NaiveForecastModel()
    assert model._compute_quantiles(SERIES, 5.0) == model._compute_quantiles(SERIES, 5.0)


def test_quantiles_do_not_cross():
    q = naive.NaiveForecastModel()._compute_quantiles(SERIES, 5.0)
    levels = [q[f"q_0.{i}"] for i in range(1, 10)]
    assert levels == sorted(levels)


def test_single_point_series_degrades_to_a_flat_band():
    assert set(naive.NaiveForecastModel()._compute_quantiles([5.0], 5.0).values()) == {5.0}
