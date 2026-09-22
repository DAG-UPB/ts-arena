"""Contract tests for the reference uploader.

Run after changing anything under `challenge-uploads/src/` or `model-services/`:

    pytest challenge-uploads/tests/

They cover the three ways a forecast can be silently lost:

* **Timestamps** (ts-arena #20) — each series must be anchored on its own last context
  point, parsed rather than string-compared, and the client must never guess a spacing it
  was not taught.
* **The upload response** (ts-arena #21) — a partially-rejected upload comes back as HTTP
  201 with `success: true`. The client must read the body and fail on it, rather than
  logging a tick based on what it sent.
* **The poll loop** (ts-arena #22) — a round is settled only by a real submission. Context
  data that is not published yet, and an upload that failed, both mean *retry*, not *done*;
  a retry must not re-submit the models that already landed, and must stop at
  `registration_end`.
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


# --- a round is settled only by a real submission (ts-arena #22) -------------
#
# `process_challenge` used to return None on four paths, two of which mean "the round is
# open, its context data just isn't published yet". The caller retired the round anyway,
# so the forecast was never made and never retried.

OPEN_ROUND = {
    "id": 77, "name": "r", "frequency": "PT1H", "horizon": "PT3H",
    "registration_end": "2099-01-01T00:00:00Z",
}
CLOSED_ROUND = dict(OPEN_ROUND, registration_end="2020-01-01T00:00:00Z")
MODELS = [("container-a", "Vendor/A"), ("container-b", "Vendor/B")]


@pytest.fixture
def uploader(monkeypatch, tmp_path):
    """The uploader with its I/O stubbed: no HTTP, no CSV in the repo."""
    monkeypatch.setattr(m, "PARTICIPATION_LOG_FILE", str(tmp_path / "participation.csv"))
    monkeypatch.setattr(m, "get_context_data", lambda rid: _ctx(
        [{"ts": (BASE + i * FREQ).isoformat(), "value": float(i)} for i in range(4)]
    ))
    monkeypatch.setattr(m, "predict_with_model",
                        lambda *a, **k: [[{"ts": "x", "value": 1.0} for _ in range(3)]])
    return m


def test_round_without_context_data_is_not_settled(uploader, monkeypatch):
    """The reported bug: not-ready must mean retry, not 'done'."""
    monkeypatch.setattr(m, "get_context_data", lambda rid: [])
    assert m.process_challenge(OPEN_ROUND, MODELS) is False


def test_round_without_usable_history_is_not_settled(uploader, monkeypatch):
    monkeypatch.setattr(m, "get_context_data", lambda rid: [{"challenge_series_name": "s", "data": []}])
    assert m.process_challenge(OPEN_ROUND, MODELS) is False


def test_a_fully_accepted_round_is_settled(uploader, monkeypatch):
    monkeypatch.setattr(m, "upload_forecasts", lambda *a, **k: _accepted())
    submitted = set()
    assert m.process_challenge(OPEN_ROUND, MODELS, submitted=submitted) is True
    assert submitted == {"Vendor/A", "Vendor/B"}


def test_failed_upload_leaves_the_round_open_for_retry(uploader, monkeypatch):
    """A failed upload used to settle the round too, burning it permanently."""
    monkeypatch.setattr(m, "upload_forecasts",
                        lambda *a, **k: (_ for _ in ()).throw(m.UploadRejected("nope")))
    assert m.process_challenge(OPEN_ROUND, MODELS) is False


def test_retry_does_not_resubmit_the_models_that_already_landed(uploader, monkeypatch):
    """Mixed outcomes: B retries, A must not upload a second time."""
    calls = []

    def flaky(round_id, model_name, forecasts):
        calls.append(model_name)
        if model_name == "Vendor/B":
            raise m.UploadRejected("transient")
        return _accepted()

    monkeypatch.setattr(m, "upload_forecasts", flaky)
    submitted = set()

    assert m.process_challenge(OPEN_ROUND, MODELS, submitted=submitted) is False
    assert submitted == {"Vendor/A"}

    m.process_challenge(OPEN_ROUND, MODELS, submitted=submitted, retry=1)
    assert calls == ["Vendor/A", "Vendor/B", "Vendor/B"]


def test_retry_stops_once_registration_has_closed(uploader, monkeypatch):
    """Bounded retry: a round nobody can upload to any more must not loop forever."""
    monkeypatch.setattr(m, "upload_forecasts",
                        lambda *a, **k: (_ for _ in ()).throw(m.UploadRejected("nope")))
    assert m.process_challenge(OPEN_ROUND, MODELS) is False
    assert m.process_challenge(CLOSED_ROUND, MODELS) is True


def test_unprocessable_round_is_settled_not_retried(uploader):
    """Nothing about a malformed round improves with waiting."""
    assert m.process_challenge({"id": 1, "name": "r"}, MODELS) is True
    assert m.process_challenge({"name": "no id"}, MODELS) is True
    assert m.process_challenge(dict(OPEN_ROUND, frequency="every other tuesday"), MODELS) is True


def test_context_data_that_never_arrives_stops_at_the_deadline(uploader, monkeypatch):
    """The other unbounded path: waiting for context data is also capped by the window."""
    monkeypatch.setattr(m, "get_context_data", lambda rid: [])
    assert m.process_challenge(OPEN_ROUND, MODELS) is False
    assert m.process_challenge(CLOSED_ROUND, MODELS) is True


def test_a_round_with_no_deadline_is_treated_as_open():
    assert m.registration_is_open({"id": 1}) is True
    assert m.registration_is_open({"id": 1, "registration_end": "not a date"}) is True
