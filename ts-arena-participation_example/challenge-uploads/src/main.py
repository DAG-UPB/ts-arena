import os
import time
import logging
import json
import re
import csv
import traceback
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import requests
from dotenv import load_dotenv
import isodate

# --- Initialization ---
load_dotenv()
time.sleep(2)

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8457")
MASTER_CONTROLLER_URL = os.environ.get("MASTER_CONTROLLER_URL", "http://localhost:8456")
REQUEST_TIMEOUT = float(os.environ.get("REQUEST_TIMEOUT", "600"))
API_KEY = os.environ.get("API_UPLOAD_KEY", "default_api_key")
CHECK_INTERVAL = int(os.environ.get("CHECK_INTERVAL", "60"))
CONFIG_FILE = os.environ.get("CONFIG_FILE", "config.json")
PARTICIPATION_LOG_FILE = os.environ.get("PARTICIPATION_LOG_FILE", "participation_log.csv")

def log_participation(round_id: str, challenge_name: str, model_container: str, 
                      api_model_name: str, status: str, message: str = ""):
    """Log participation details to CSV file"""
    file_exists = os.path.exists(PARTICIPATION_LOG_FILE)
    
    try:
        with open(PARTICIPATION_LOG_FILE, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["Timestamp", "Challenge ID", "Challenge Name", "Model Container", 
                                 "API Model Name", "Status", "Message"])
            
            writer.writerow([
                datetime.now().isoformat(),
                round_id,
                challenge_name,
                model_container,
                api_model_name,
                status,
                message
            ])
    except Exception as e:
        logger.error(f"Error writing to participation log: {e}")

# --- HTTP Helper Functions ---
def http_get(path: str, with_auth: bool = True) -> requests.Response:
    # Handle double slashes - strip trailing slash from base URL and ensure path starts with /
    base = API_BASE_URL.rstrip('/')
    if not path.startswith('/'):
        path = '/' + path
    url = f"{base}{path}"
    headers = {"X-API-Key": API_KEY} if with_auth else {}
    logger.debug(f"GET {url} (auth={with_auth})")
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers=headers)
        resp.raise_for_status()
        return resp
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP Error beim GET {url}: {e}")
        logger.error(f"  Status Code: {e.response.status_code}")
        logger.error(f"  Response: {e.response.text[:500]}")
        raise


def http_post(path: str, json_data: Dict[str, Any]) -> requests.Response:
    # Handle double slashes
    base = API_BASE_URL.rstrip('/')
    if not path.startswith('/'):
        path = '/' + path
    url = f"{base}{path}"
    logger.debug(f"POST {url}")
    try:
        resp = requests.post(url, json=json_data, timeout=REQUEST_TIMEOUT, headers={"X-API-Key": API_KEY})
        resp.raise_for_status()
        return resp
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP Error during POST {url}: {e}")
        logger.error(f"  Status Code: {e.response.status_code}")
        logger.error(f"  Response: {e.response.text[:500]}")
        raise


def master_http_post(path: str, json_data: Dict[str, Any]) -> requests.Response:
    url = f"{MASTER_CONTROLLER_URL}{path}"
    logger.debug(f"MASTER POST {url} payload keys: {json_data.keys()}")
    resp = requests.post(url, json=json_data, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp


# --- Model & Config Utils ---
def load_config() -> Dict[str, Any]:
    """Load config file"""
    # Try current dir, script dir and parent dirs
    script_dir = os.path.dirname(os.path.abspath(__file__))
    paths = [
        CONFIG_FILE, 
        os.path.join(script_dir, CONFIG_FILE),
        os.path.join("..", CONFIG_FILE), 
        "/app/config.json"
    ]
    for path in paths:
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    logger.info(f"Loading config from {path}")
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading config {path}: {e}")
                return {}
    logger.warning(f"No config file found (searched in {paths})")
    return {}


def fetch_registered_models() -> List[Dict[str, Any]]:
    """Fetch registered models from API (returns only models owned by the API key's user)"""
    try:
        url = f"{API_BASE_URL}/api/v1/models"
        headers = {"X-API-Key": API_KEY}
        logger.debug(f"GET {url}")

        resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"Error fetching registered models: {e}")
        return []


def resolve_models(config: Dict[str, Any], registered_models: List[Dict[str, Any]]) -> List[Tuple[str, str]]:
    """
    Match config keys (container names) with registered models.
    Returns: List of (container_name, api_model_name)
    """
    resolved = []
    
    # Create lookup for registered models by name
    reg_lookup = {m.get("name"): m for m in registered_models}
    
    for container_name, conf_data in config.items():
        conf_model_name = conf_data.get("name")
        logger.info(f"Resolving model for container '{container_name}': {conf_model_name}")
        if not conf_model_name:
            continue
            
        if conf_model_name in reg_lookup:
            # Match found
            resolved.append((container_name, conf_model_name))
            logger.info(f"Model matched: Container '{container_name}' -> API Name '{conf_model_name}'")
        else:
            logger.warning(f"Model from config '{container_name}' ({conf_model_name}) not found in API")
            
    return resolved


# --- API Utils ---
def get_all_challenges() -> List[Dict[str, Any]]:
    """Fetch all available challenge rounds (registration phase)"""
    try:
        resp = http_get("/api/v1/challenge/rounds?status=registration", with_auth=True)
        return resp.json() or []
    except Exception as e:
        logger.error(f"Error fetching challenges: {e}")
        return []

def get_context_data(round_id: str) -> List[Dict[str, Any]]:
    """Fetch context data for a challenge round"""
    try:
        resp = http_get(f"/api/v1/challenge/rounds/{round_id}/context-data", with_auth=True)
        return resp.json() or []
    except Exception as e:
        logger.error(f"Error fetching context data for round {round_id}: {e}")
        return []


# --- Frequency Parsing ---
def parse_frequency(frequency_str: str) -> timedelta:
    """Parse frequency string to timedelta (supports ISO 8601 duration)"""
    frequency_str = (frequency_str or "").strip()
    
    # Try ISO 8601 duration first (e.g. 'PT1H', 'PT15M')
    if frequency_str.startswith('P'):
        try:
            return isodate.parse_duration(frequency_str)
        except Exception as e:
            logger.warning(f"Error parsing ISO frequency '{frequency_str}': {e}")
    
    # Legacy / Human-readable formats
    lower_str = frequency_str.lower()
    patterns = [
        (r"(\d+)\s*(?:minute|minutes|min|mins)", lambda m: timedelta(minutes=int(m.group(1)))),
        (r"(\d+)\s*(?:hour|hours|hr|hrs|h)", lambda m: timedelta(hours=int(m.group(1)))),
        (r"(\d+)\s*(?:day|days|d)", lambda m: timedelta(days=int(m.group(1)))),
        (r"(\d+)\s*(?:second|seconds|sec|secs|s)", lambda m: timedelta(seconds=int(m.group(1)))),
    ]
    
    for pattern, converter in patterns:
        match = re.match(pattern, lower_str)
        if match:
            return converter(match)
    
    # No hourly fallback (ts-arena #20). A frequency this client cannot parse means a
    # challenge cadence it was never taught; guessing hourly produced correctly-counted
    # points at wrong spacing, which the platform accepted and scored. Failing here costs
    # one round and says exactly what is wrong.
    raise ValueError(
        f"Unsupported challenge frequency '{frequency_str}'. Add it to parse_frequency() "
        f"rather than letting the client guess the spacing of your forecast."
    )


def parse_horizon(horizon_str: str, frequency) -> int:
    """Parse horizon string (e.g. 'PT1H') to number of steps"""
    try:
        # Use isodate to parse the duration
        duration = isodate.parse_duration(horizon_str)
        
        # Convert duration to seconds
        total_seconds = int(duration.total_seconds())
        
        # Calculate number of steps based on frequency
        step_count = total_seconds // int(frequency.total_seconds())
        
        return step_count
    except Exception as e:
        logger.warning(f"Error parsing horizon string '{horizon_str}': {e}")
        return 1  # Default to 1 step


def parse_timestamp(ts_str: str) -> datetime:
    """Parse an ISO-8601 timestamp from the API into an aware datetime."""
    return datetime.fromisoformat(ts_str.replace('Z', '+00:00'))


# --- Context Utils ---
def extract_history_from_context(context_data: List[Dict[str, Any]]) -> Tuple[List[List[Dict[str, Any]]], List[str], List[datetime]]:
    """
    Extract history data from context data in HistoryItem format
    Returns: (histories, series_names, max_timestamps)
    
    histories is a list of series, where each series is a list of
    HistoryItem dicts: [{"ts": "...", "value": ...}, ...]
    """
    histories = []
    series_names = []
    max_timestamps = []
    
    for serie in context_data:
        name = serie.get('challenge_series_name', f'serie_{len(series_names)}')
        data = serie.get('data', [])
        
        if not data:
            logger.warning(f"Series {name} has no data")
            continue
        
        # Extract as HistoryItem format (ts + value dicts)
        history_items = [{"ts": item['ts'], "value": item['value']} for item in data]

        # Find the last context timestamp. Parse BEFORE comparing: max() over raw ISO
        # strings is a lexicographic comparison, which only happens to be right while
        # every timestamp shares one format and offset. Mixed 'Z' / '+00:00', or differing
        # microsecond precision, silently picks the wrong anchor (ts-arena #20).
        max_dt = max(parse_timestamp(item['ts']) for item in data)
        
        histories.append(history_items)
        series_names.append(name)
        max_timestamps.append(max_dt)
    
    return histories, series_names, max_timestamps


# --- Prediction ---
def predict_with_model(model_name: str, histories: List[List[Dict[str, Any]]], horizon: int, freq: str) -> Optional[List[List[Dict[str, Any]]]]:
    """
    Send predict request to Master Controller
    
    Args:
        model_name: Name of the model
        histories: List of series, each series is a list of HistoryItem dicts
                   [{"ts": "...", "value": ...}, ...]
        horizon: Number of prediction steps
        freq: Frequency string (e.g. "15min", "h", "D")
    
    Returns:
        List of forecast lists or None on error
    """
    if not histories:
        logger.warning(f"No histories for model {model_name} – skipping prediction")
        return None

    payload = {
        "model_name": model_name, 
        "history": histories, 
        "horizon": horizon,
        "freq": freq
    }
    
    try:
        resp = master_http_post("/predict", json_data=payload)
        result = resp.json() or {}
        preds = result.get("prediction")

        if not preds or not isinstance(preds, list):
            logger.warning(f"No valid prediction returned for model {model_name}")
            return None

        return preds
    except Exception as e:
        logger.error(f"Error during prediction with model {model_name}: {e}")
        # Re-raise to be caught by the main loop for logging
        raise


# --- Forecast Formatting ---
def expected_forecast_timestamps(
    context_edge: datetime,
    frequency_delta: timedelta,
    horizon_steps: int,
) -> List[str]:
    """The timestamps a forecast for this series must carry.

    `context_edge + k * frequency` for k = 1..horizon_steps — the same rule the platform
    validates against. Derived per series, because series lag: the round's global start
    time sits one or more steps after a lagging series' own last context point.
    """
    return [
        (context_edge + k * frequency_delta).isoformat()
        for k in range(1, horizon_steps + 1)
    ]


def format_forecasts(
    prediction: Union[List[Dict], List[List[Dict]], List[List[float]]], 
    series_names: List[str], 
    max_timestamps: List[datetime],
    frequency_delta: timedelta,
    horizon_steps: int,
) -> List[Dict[str, Any]]:
    """
    Format predictions into upload format.

    The timestamps are generated HERE, from the per-series context edge this client already
    computed, and they overwrite whatever the model service returned (ts-arena #20).

    Previously this function took `max_timestamps` and `frequency_delta` and used neither:
    the timestamps that reached the API were the model service's, anchored on
    `series[-1].ts` — the last element in *array order*. That was correct only for as long
    as the API happened to return context points sorted by ts. Nothing in the API contract
    promised that, so a reordering upstream would have shifted every forecast from every
    copy of this client at once, silently and without an error.
    """
    forecasts_array = []
    
    # Handle different prediction formats
    if isinstance(prediction, list) and len(prediction) > 0:
        first_item = prediction[0]
        
        if isinstance(first_item, dict) and 'ts' in first_item:
            # Single series
            series_forecasts = _retimestamp(
                prediction, max_timestamps[0], frequency_delta, horizon_steps,
                series_names[0],
            )
            forecasts_array.append({
                "challenge_series_name": series_names[0],
                "forecasts": series_forecasts
             })
        elif isinstance(first_item, list) and len(first_item) > 0 and isinstance(first_item[0], dict) and 'ts' in first_item[0]:
            # Multiple series
            for name, context_edge, series_forecasts in zip(series_names, max_timestamps, prediction):
                forecasts_array.append({
                    "challenge_series_name": name,
                    "forecasts": _retimestamp(
                        series_forecasts, context_edge, frequency_delta, horizon_steps, name,
                    )
                })
    return forecasts_array


def _retimestamp(
    series_forecasts: List[Dict[str, Any]],
    context_edge: datetime,
    frequency_delta: timedelta,
    horizon_steps: int,
    series_name: str,
) -> List[Dict[str, Any]]:
    """Replace the model service's timestamps with the ones the round actually expects."""
    expected = expected_forecast_timestamps(context_edge, frequency_delta, horizon_steps)

    if len(series_forecasts) != len(expected):
        raise ValueError(
            f"Series '{series_name}': model returned {len(series_forecasts)} points but the "
            f"round expects {len(expected)}. Refusing to upload a payload the platform "
            f"would reject."
        )

    return [
        {**point, "ts": ts}
        for point, ts in zip(series_forecasts, expected)
    ]


# --- Upload ---
class UploadRejected(Exception):
    """The API accepted the request but rejected some or all of the forecast."""


def upload_forecasts(
    round_id: int, model_name: str, forecasts: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Upload forecasts for a challenge round, and check what the platform actually stored.

    A partially-accepted upload comes back as **HTTP 201**: the API sets `success` to
    "anything landed at all", and reports per-series rejections in `errors`. So
    `raise_for_status()` is not enough — this function used to stop there and log a tick
    based on how many series it *sent*, which meant an upload could be almost entirely
    rejected while the log read `✓ Upload successful` (ts-arena #21).

    Returns the parsed response so the caller can log the platform's own numbers.
    Raises UploadRejected if anything was refused.
    """
    payload = {
        "round_id": round_id,
        "model_name": model_name,
        "forecasts": forecasts
    }
    expected_points = sum(len(series["forecasts"]) for series in forecasts)

    try:
        resp = http_post("/api/v1/forecasts/upload", json_data=payload)
    except Exception as e:
        logger.error(f"✗ Error uploading for round {round_id}, model {model_name}: {e}")
        raise

    try:
        body = resp.json() or {}
    except ValueError:
        logger.warning("Upload response was not JSON; cannot verify what was stored")
        return {}

    # `warnings` and the point/probabilistic split arrive from newer api-portal versions
    # only. Read everything defensively so this client keeps working against both.
    errors = body.get("errors") or []
    warnings = body.get("warnings") or []
    rejections = [e for e in errors if e not in warnings]

    inserted = body.get("points_inserted", body.get("forecasts_inserted", 0))
    probabilistic = body.get("probabilistic_points_inserted")
    model_id = body.get("model_id")

    stored = f"{inserted}/{expected_points} points"
    if probabilistic is not None:
        stored += f", {probabilistic} with quantiles"
    if model_id is not None:
        stored += f", model_id={model_id}"

    for warning in warnings:
        logger.warning(f"  upload warning: {warning}")

    if rejections or inserted < expected_points:
        for rejection in rejections:
            logger.error(f"  upload rejected: {rejection}")
        raise UploadRejected(
            f"round {round_id}, model {model_name}: stored {stored}"
            + (f"; {len(rejections)} rejection(s): {rejections}" if rejections else "")
        )

    logger.info(f"✓ Upload verified for round {round_id}, model {model_name}: {stored}")
    return body


# --- Main ---
def map_model_frequency(frequency_str: str) -> str:
    """Map a challenge frequency onto the frequency string the model services expect.

    Raises ValueError rather than falling back to hourly: PT5M and PT15M are different
    challenges, and guessing silently mis-spaces every point (ts-arena #20).
    """
    freq_mapping = {
        "1 minute": "1min", "15 minutes": "15min", "30 minutes": "30min",
        "1 hour": "h", "1 day": "D", "1 week": "W", "1 month": "M",
        "PT1M": "1min", "PT15M": "15min", "PT30M": "30min",
        "PT1H": "h", "P1D": "D", "P1W": "W", "P1M": "M"
    }
    model_freq = freq_mapping.get(frequency_str) or freq_mapping.get(frequency_str.lower())
    if model_freq:
        return model_freq

    # Generic ISO duration mapping
    if frequency_str.startswith('PT'):
        if 'H' in frequency_str:
            return 'h'
        # No 'any PT..M means 15min' guess: PT5M and PT15M are different challenges,
        # and the wrong one silently mis-spaces every point (ts-arena #20).
    elif frequency_str.startswith('P'):
        if 'D' in frequency_str: return 'D'
        if 'W' in frequency_str: return 'W'
        if 'M' in frequency_str: return 'M'

    raise ValueError(
        f"Could not map challenge frequency '{frequency_str}' to a model frequency "
        f"string. Add it to freq_mapping rather than defaulting to hourly."
    )


def registration_is_open(challenge: Dict[str, Any]) -> bool:
    """Is this round still accepting uploads?

    Used to bound retries (ts-arena #22). A round whose context data never materialises
    must not be re-predicted forever — once `registration_end` is past, nothing we upload
    can be accepted, so stop.

    A round that does not report `registration_end`, or reports one we cannot parse, is
    treated as open: the uploader's job is to try, and the API is the authority on the
    deadline.
    """
    raw = challenge.get("registration_end")
    if not raw:
        return True
    try:
        deadline = parse_timestamp(raw)
    except Exception:
        logger.debug(f"Unparseable registration_end {raw!r}; treating the round as open")
        return True
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) < deadline


def process_challenge(challenge: Dict[str, Any], active_models: List[Tuple[str, str]],
                      submitted: Optional[Set[str]] = None,
                      refused: Optional[Set[str]] = None, retry: int = 0) -> bool:
    """Process a single challenge round.

    Returns **True when the round is settled** — every active model has either uploaded
    successfully or is permanently unprocessable — and **False when it should be retried**
    on a later poll.

    This return value is the whole point (ts-arena #22). This function used to return
    `None` on four different paths, two of which mean "the round is open, its context data
    just isn't published yet". The caller could not tell those apart from a completed
    submission, so it retired the round anyway and the forecast was silently never made.

    `submitted` is the set of model names that already uploaded for this round in an
    earlier pass; it is **mutated in place** as models succeed. Passing it back on a retry
    is what keeps a partially successful round from double-submitting the models that
    already landed.

    `refused` is the same idea for models the platform **rejected on content** — an unknown
    series name, a wrong point count. Those are deterministic: the identical payload gets
    refused identically, so re-predicting them every poll until the window closed would be
    pure waste. They are dropped from the round instead. Only transient failures — a
    connection error or 5xx, or a prediction that did not come back — keep the round open.

    `retry` is how many times this round has already come back not-ready. It is a logging
    knob only: the preamble and the "not ready" line are worth one INFO the first time and
    DEBUG on every repeat after that, so a 60 s poll does not flood the log.
    """
    round_id = challenge.get("id")
    challenge_name = challenge.get("name", "Unknown")
    if submitted is None:
        submitted = set()
    if refused is None:
        refused = set()

    # First look at this round gets the full preamble; the repeats go to DEBUG.
    detail = logger.info if retry == 0 else logger.debug
    not_ready = logger.warning if retry == 0 else logger.debug

    if not round_id:
        logger.warning("Skipped challenge without ID")
        return True  # settled: unprocessable, and no amount of waiting changes that

    detail(f"Processing challenge round {round_id}: {challenge_name}")

    # Extract frequency and horizon (expected in the rounds response)
    frequency_str = challenge.get("frequency")
    horizon_str = challenge.get("horizon")

    if not frequency_str or not horizon_str:
        logger.warning(f"Challenge round {round_id} missing frequency or horizon")
        return True  # settled: unprocessable

    # A frequency we cannot map is deterministic — it will never become mappable, so this
    # settles the round rather than retrying it every poll until registration closes.
    try:
        frequency_delta = parse_frequency(frequency_str)
        horizon_steps = parse_horizon(horizon_str, frequency_delta)
        model_freq = map_model_frequency(frequency_str)
    except ValueError as e:
        logger.error(f"Round {round_id}: {e}")
        for container_name, api_model_name in active_models:
            log_participation(str(round_id), challenge_name, container_name, api_model_name,
                              "FAILURE", str(e))
        return True  # settled: unprocessable

    detail(f"  Frequency: {frequency_str} -> {frequency_delta}")
    detail(f"  Horizon: {horizon_str} -> {horizon_steps} steps")

    def wait_for(what: str) -> bool:
        """Retry while the round can still accept an upload; give up once it cannot.

        The deadline check belongs here too, not only on the upload path: a round whose
        context data never appears would otherwise be re-polled forever.
        """
        if registration_is_open(challenge):
            not_ready(f"{what} for round {round_id} yet - will retry next poll")
            return False
        logger.error(f"Round {round_id}: registration closed with {what.lower()}")
        return True

    # Fetch context data. Not being published yet is the normal case for a round that has
    # just opened — it is a retry, not a failure.
    context_data = get_context_data(str(round_id))
    if not context_data:
        return wait_for("No context data")

    histories, series_names, max_timestamps = extract_history_from_context(context_data)
    if not histories:
        return wait_for("No usable history data")

    logger.info(f"  {len(histories)} series found")

    # Process each model that has neither uploaded nor been refused for this round.
    settled_models = submitted | refused
    pending = [(c, a) for c, a in active_models if a not in settled_models]
    if settled_models:
        logger.info(f"  Skipping {len(submitted)} model(s) already uploaded and "
                    f"{len(refused)} the platform refused for this round")

    for container_name, api_model_name in pending:
        logger.info(f"  Creating predictions with container {container_name} for model {api_model_name}")

        try:
            # Predict uses container_name
            predictions = predict_with_model(container_name, histories, horizon_steps, model_freq)
            if not predictions:
                logger.warning(f"  No predictions for container {container_name}")
                log_participation(str(round_id), challenge_name, container_name, api_model_name, "FAILURE", "Prediction returned None or invalid format")
                continue

            # Format forecasts
            forecasts = format_forecasts(
                predictions, series_names, max_timestamps, frequency_delta, horizon_steps,
            )

            # Upload uses api_model_name (e.g., 'Statistical/Naive')
            result = upload_forecasts(int(round_id), api_model_name, forecasts)
            # Only a verified upload counts as submitted.
            submitted.add(api_model_name)
            # Report what the PLATFORM stored, never what we sent.
            log_participation(
                str(round_id), challenge_name, container_name, api_model_name, "SUCCESS",
                f"Stored {result.get('points_inserted', result.get('forecasts_inserted', '?'))} points "
                f"({result.get('probabilistic_points_inserted', '?')} with quantiles) "
                f"across {len(forecasts)} series"
            )

        except UploadRejected as e:
            # Content the platform refused. Deterministic — do not re-attempt this round.
            refused.add(api_model_name)
            logger.error(f"Upload refused for {container_name}, not retrying this round: {e}")
            log_participation(str(round_id), challenge_name, container_name, api_model_name,
                              "FAILURE", f"refused: {e}")

        except Exception as e:
            error_details = traceback.format_exc()
            logger.error(f"Error processing model {container_name}: {e}")
            log_participation(str(round_id), challenge_name, container_name, api_model_name, "FAILURE", f"{str(e)}\n{error_details}")

    outstanding = [a for _, a in active_models if a not in submitted and a not in refused]
    if not outstanding:
        if refused:
            logger.error(
                f"Round {round_id} settled with {len(refused)} model(s) refused "
                f"({', '.join(sorted(refused))})"
            )
        return True

    # Something did not land. Retry it while the round can still accept an upload —
    # a transient API error or a model container that is still warming up is exactly
    # what the remaining window is for.
    if registration_is_open(challenge):
        logger.warning(
            f"Round {round_id}: {len(outstanding)} model(s) did not upload "
            f"({', '.join(outstanding)}) - will retry while registration is open"
        )
        return False

    logger.error(
        f"Round {round_id}: registration closed with {len(outstanding)} model(s) "
        f"never uploaded ({', '.join(outstanding)})"
    )
    return True  # settled: the window is gone, retrying cannot help


def main_loop():
    """Main loop: Check regularly for new challenges"""
    logger.info("Challenge Upload Service started")
    logger.info(f"API Base URL: {API_BASE_URL}")
    logger.info(f"Master Controller URL: {MASTER_CONTROLLER_URL}")
    logger.info(f"Check Interval: {CHECK_INTERVAL}s")
    
    # Model initialization
    config = load_config()
    registered_models = fetch_registered_models()
    logger.info(f"Registered models: {registered_models}")
    active_models = resolve_models(config, registered_models)
    
    if not active_models:
        logger.warning("No active models found. Check config and API.")
    else:
        logger.info(f"Active models: {len(active_models)}")
        for container, api_name in active_models:
            logger.info(f"  - {container} -> {api_name}")
    
    # A round leaves `pending` for `processed_challenges` only once process_challenge
    # reports it settled. `pending` remembers, per round, which models already uploaded
    # and how many polls it has waited, so a retry neither re-submits nor re-floods.
    processed_challenges = set()
    pending: Dict[Any, Dict[str, Any]] = {}

    while True:
        try:
            # Fetch all challenges
            challenges = get_all_challenges()
            logger.info(f"Found challenges: {len(challenges)}")

            # A round that has dropped out of the registration list can no longer be
            # uploaded to, so stop carrying its retry state.
            open_ids = {c.get("id") for c in challenges}
            for gone in [rid for rid in pending if rid not in open_ids]:
                state = pending.pop(gone)
                logger.error(
                    f"Round {gone} left the registration list after {state['retry']} "
                    f"retries with {len(state['submitted'])} model(s) uploaded"
                )

            for challenge in challenges:
                round_id = challenge.get("id")
                
                # Check if already processed
                if round_id in processed_challenges:
                    logger.debug(f"Round {round_id} already processed, skipping")
                    continue
                
                state = pending.setdefault(
                    round_id, {"retry": 0, "submitted": set(), "refused": set()})
                retry = state["retry"]

                # Process challenge
                try:
                    settled = process_challenge(
                        challenge, active_models,
                        submitted=state["submitted"], refused=state["refused"],
                        retry=retry,
                    )
                except Exception as e:
                    # An unexpected error is not evidence the round is done. Leave it in
                    # `pending` so the next poll tries again.
                    logger.error(f"Error processing round {round_id}: {e}")
                    state["retry"] = retry + 1
                    continue

                if settled:
                    processed_challenges.add(round_id)
                    pending.pop(round_id, None)
                    if retry:
                        logger.info(
                            f"Round {round_id} settled after {retry} retries "
                            f"(~{retry * CHECK_INTERVAL}s wait)"
                        )
                else:
                    state["retry"] = retry + 1
                    if retry == 0:
                        logger.info(
                            f"Round {round_id} not ready yet - retrying every "
                            f"{CHECK_INTERVAL}s while registration is open"
                        )
            
            # Wait for next check
            logger.info(f"Waiting {CHECK_INTERVAL}s for next check...")
            time.sleep(CHECK_INTERVAL)
            
        except KeyboardInterrupt:
            logger.info("Service stopping...")
            break
        except Exception as e:
            logger.error(f"Error in main loop: {e}")
            time.sleep(CHECK_INTERVAL)


def main_once():
    """One-time execution for testing"""
    logger.info("One-time challenge processing")
    
    # Model initialization
    config = load_config()
    registered_models = fetch_registered_models()
    active_models = resolve_models(config, registered_models)
    
    if not active_models:
        logger.warning("No active models found.")
        return

    challenges = get_all_challenges()
    logger.info(f"Found challenges: {len(challenges)}")
    
    for challenge in challenges:
        # One-shot: there is no next poll, so an unsettled round is reported, not retried.
        if not process_challenge(challenge, active_models):
            logger.warning(
                f"Round {challenge.get('id')} did not fully submit. "
                f"Re-run, or use the service loop, while registration is still open."
            )


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "once":
        main_once()
    else:
        main_loop()