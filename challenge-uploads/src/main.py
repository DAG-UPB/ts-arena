import os
import time
import logging
import json
import re
import csv
import traceback
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

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
USER_ID = os.environ.get("USER_ID")
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
    url = f"{API_BASE_URL}{path}"
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
    url = f"{API_BASE_URL}{path}"
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
    """Fetch registered models from API"""
    if not USER_ID:
        logger.warning("USER_ID not set, cannot fetch models")
        return []
    
    try:
        # Set user_id parameter
        params = {"user_id": USER_ID}
        url = f"{API_BASE_URL}/api/v1/models"
        headers = {"X-API-Key": API_KEY}
        logger.debug(f"GET {url} params={params}")
        
        resp = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
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
    """Fetch all available challenges (registration phase)"""
    try:
        resp = http_get("/api/v1/challenge/", with_auth=True)
        return resp.json() or []
    except Exception as e:
        logger.error(f"Error fetching challenges: {e}")
        return []

def get_context_data(round_id: str) -> List[Dict[str, Any]]:
    """Fetch context data for a challenge round"""
    try:
        resp = http_get(f"/api/v1/challenge/{round_id}/context-data", with_auth=True)
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
    
    logger.warning(f"Could not parse frequency '{frequency_str}', using 1 hour as default")
    return timedelta(hours=1)


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
        
        # Find maximum timestamp
        timestamps = [item['ts'] for item in data]
        max_ts_str = max(timestamps)
        max_dt = datetime.fromisoformat(max_ts_str.replace('Z', '+00:00'))
        
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
def format_forecasts(
    prediction: Union[List[Dict], List[List[Dict]], List[List[float]]], 
    series_names: List[str], 
    max_timestamps: List[datetime],
    frequency_delta: timedelta
) -> List[Dict[str, Any]]:
    """
    Format predictions into upload format
    """
    forecasts_array = []
    
    # Handle different prediction formats
    if isinstance(prediction, list) and len(prediction) > 0:
        first_item = prediction[0]
        
        if isinstance(first_item, dict) and 'ts' in first_item:
            # Single series
            forecasts_array.append({
                "challenge_series_name": series_names[0],
                "forecasts": prediction
             })
        elif isinstance(first_item, list) and len(first_item) > 0 and isinstance(first_item[0], dict) and 'ts' in first_item[0]:
            # Multiple series
            for i, (name, series_forecasts) in enumerate(zip(series_names, prediction)):
                forecasts_array.append({
                    "challenge_series_name": name,
                    "forecasts": series_forecasts
                })
    return forecasts_array


# --- Upload ---
def upload_forecasts(round_id: int, model_name: str, forecasts: List[Dict[str, Any]]):
    """Upload forecasts for a challenge round"""
    payload = {
        "round_id": round_id,
        "model_name": model_name,
        "forecasts": forecasts
    }
    
    try:
        http_post("/api/v1/forecasts/upload", json_data=payload)
        logger.info(f"✓ Upload successful for round {round_id}, model {model_name}: {len(forecasts)} series")
    except Exception as e:
        logger.error(f"✗ Error uploading for round {round_id}, model {model_name}: {e}")
        raise


# --- Main ---
def process_challenge(challenge: Dict[str, Any], active_models: List[Tuple[str, str]]):
    """Process a single challenge round"""
    round_id = challenge.get("id")
    challenge_name = challenge.get("name", "Unknown")
    
    if not round_id:
        logger.warning("Skipped challenge without ID")
        return
    
    logger.info(f"Processing challenge round {round_id}: {challenge_name}")
    
    # Extract frequency and horizon (expected in the rounds response)
    frequency_str = challenge.get("frequency")
    horizon_str = challenge.get("horizon")
    
    if not frequency_str or not horizon_str:
        logger.warning(f"Challenge round {round_id} missing frequency or horizon")
        return
    
    frequency_delta = parse_frequency(frequency_str)
    horizon_steps = parse_horizon(horizon_str, frequency_delta)
    
    logger.info(f"  Frequency: {frequency_str} -> {frequency_delta}")
    logger.info(f"  Horizon: {horizon_str} -> {horizon_steps} steps")
    
    # Fetch context data
    context_data = get_context_data(str(round_id))
    if not context_data:
        logger.warning(f"No context data for round {round_id}")
        return
    
    # Extract history in HistoryItem format
    histories, series_names, max_timestamps = extract_history_from_context(context_data)
    if not histories:
        logger.warning(f"No usable history data for round {round_id}")
        return
    
    logger.info(f"  {len(histories)} series found")
    
    # Convert frequency to model format
    freq_mapping = {
        "1 minute": "1min", "15 minutes": "15min", "30 minutes": "30min",
        "1 hour": "h", "1 day": "D", "1 week": "W", "1 month": "M",
        "PT1M": "1min", "PT15M": "15min", "PT30M": "30min",
        "PT1H": "h", "P1D": "D", "P1W": "W", "P1M": "M"
    }
    model_freq = freq_mapping.get(frequency_str) or freq_mapping.get(frequency_str.lower())
    
    if not model_freq:
        # Generic ISO duration mapping
        if frequency_str.startswith('PT'):
            if 'H' in frequency_str: model_freq = 'h'
            elif 'M' in frequency_str: model_freq = '15min' # default min
        elif frequency_str.startswith('P'):
            if 'D' in frequency_str: model_freq = 'D'
            elif 'W' in frequency_str: model_freq = 'W'
            elif 'M' in frequency_str: model_freq = 'M'
        
        if not model_freq:
            logger.warning(f"Could not map frequency '{frequency_str}' to model format, using 'h'")
            model_freq = 'h'
    
    # Process for each model in active_models
    for container_name, api_model_name in active_models:
        logger.info(f"  Creating predictions with container {container_name} for model {api_model_name}")
        
        try:
            # Predict uses container_name
            predictions = predict_with_model(container_name, histories, horizon_steps, model_freq)
            if not predictions:
                logger.warning(f"  No predictions for container {container_name}")
                log_participation(str(round_id), challenge_name, container_name, api_model_name, "FAILURE", "Prediction returned None or invalid format")
                continue
            
            # Format forecasts
            forecasts = format_forecasts(predictions, series_names, max_timestamps, frequency_delta)
            
            # Upload uses api_model_name
            upload_forecasts(int(round_id), container_name, forecasts)
            log_participation(str(round_id), challenge_name, container_name, api_model_name, "SUCCESS", f"Uploaded {len(forecasts)} series")
            
        except Exception as e:
            error_details = traceback.format_exc()
            logger.error(f"Error processing model {container_name}: {e}")
            log_participation(str(round_id), challenge_name, container_name, api_model_name, "FAILURE", f"{str(e)}\n{error_details}")


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
    
    processed_challenges = set()
    
    while True:
        try:
            # Fetch all challenges
            challenges = get_all_challenges()
            logger.info(f"Found challenges: {len(challenges)}")
            
            for challenge in challenges:
                round_id = challenge.get("id")
                
                # Check if already processed
                if round_id in processed_challenges:
                    logger.debug(f"Round {round_id} already processed, skipping")
                    continue
                
                # Process challenge
                try:
                    process_challenge(challenge, active_models)
                    processed_challenges.add(round_id)
                except Exception as e:
                    logger.error(f"Error processing round {round_id}: {e}")
            
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
        process_challenge(challenge, active_models)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "once":
        main_once()
    else:
        main_loop()