# challenge-uploads: Automatic Challenge Participant

This service automatically monitors available challenges and participates during the registration period. It uses the configured models from the Master Controller to generate and upload predictions.

## Prerequisites

Before using this service, you need access to a running **ts-arena-backend** instance:

1. **User Account**: A user must be created in the backend
2. **API Key**: An API key must be generated for that user
3. **Backend Running**: The `api-portal` service must be accessible

If you're self-hosting ts-arena-backend, see: https://github.com/DAG-UPB/ts-arena-backend

## Quick Start: Complete Setup

### Step 1: Configure Environment

Create/edit your `.env` file in the project root:

```bash
# API Portal connection (ts-arena-backend)
API_BASE_URL=http://your-api-portal-url
API_UPLOAD_KEY=your_api_key_here
USER_ID=your_user_id_here

# Master Controller (for model inference - set automatically via Docker Compose)
MASTER_CONTROLLER_URL=http://master-controller-api:8000

# Optional
CHECK_INTERVAL=300
LOG_LEVEL=INFO
REQUEST_TIMEOUT=600
```

### Step 2: Register Your Model

```bash
cd challenge-uploads/src
pip install -r ../requirements.txt

# Check API connectivity
python register_models.py --check

# Register all models from config.json
python register_models.py

# List your registered models
python register_models.py --list
```

### Step 3: Start the Service

```bash
# With Docker Compose (recommended)
docker-compose up -d

# Or standalone for testing
python src/main.py once    # One-time run
python src/main.py         # Continuous mode
```

## How it works

The service performs the following steps:

1. **Model Resolution**: Loads `config.json` and matches container names against models registered with the API (via `GET /api/v1/models?user_id=...`)
2. **Challenge Polling**: Regularly polls active challenge rounds via `GET /api/v1/challenge/rounds?status=registration`
3. **Context Data**: Loads historical data via `GET /api/v1/challenge/rounds/{round_id}/context-data` with API key
4. **Prediction**: Sends batch history data to the Master Controller (`POST http://master-controller-api:8000/predict`) for each configured model
5. **Formatting**: Formats predictions according to API specification with correct timestamps based on frequency
6. **Upload**: Uploads forecasts via `POST /api/v1/forecasts/upload` with `round_id` and `model_name`

**Note**: Uploading forecasts automatically registers your model as a challenge participant. No separate registration step needed per challenge!

## Configuration

### Environment variables in `.env`:

| Variable | Description | Default |
|----------|-------------|---------|
| `API_BASE_URL` | URL of the ts-arena-backend API Portal | `http://localhost:8457` |
| `API_UPLOAD_KEY` | Your API key (linked to your user) | **Required** |
| `USER_ID` | Your user ID in the API (for fetching registered models) | **Required** |
| `MASTER_CONTROLLER_URL` | URL of the Master Controller | `http://localhost:8456` |
| `CHECK_INTERVAL` | Seconds between challenge checks | `60` |
| `REQUEST_TIMEOUT` | HTTP request timeout in seconds | `600` |
| `LOG_LEVEL` | Logging level | `INFO` |
| `CONFIG_FILE` | Path to model config file | `config.json` |
| `PARTICIPATION_LOG_FILE` | Path to CSV participation log | `participation_log.csv` |

### Model Configuration (config.json)

Add your models to `src/config.json`:

```json
{
  "naive-forecast": {
    "name": "Statistical/Naive",
    "model_type": "Baseline",
    "model_family": "Statistical",
    "model_size": 0,
    "hosting": "self-hosted",
    "architecture": "rule-based",
    "pretraining_data": null,
    "publishing_date": null,
    "parameters": {}
  }
}
```

- The **key** (e.g., `naive-forecast`) must match the Docker container name used for inference.
- The **`name`** field is what gets registered with the API and used in forecast uploads.
- The service matches these against models registered via `register_models.py`.

## Forecast Upload Format

When uploading forecasts, use this payload format:

```json
{
  "round_id": 12098,
  "model_name": "Statistical/Naive",
  "forecasts": [
    {
      "challenge_series_name": "Energy_Series_1",
      "forecasts": [
        {"ts": "2026-02-02T10:15:00Z", "value": 150.5},
        {"ts": "2026-02-02T10:30:00Z", "value": 152.3}
      ]
    }
  ]
}
```

- `round_id`: The challenge round ID (from the rounds endpoint)
- `model_name`: The registered model name (from config.json `name` field)
- `challenge_series_name`: From the context data response
- `ts`: ISO 8601 timestamp
- `value`: Predicted value

## Build & Run

### With Docker Compose

```yaml
challenge-uploads:
  build:
    context: ./challenge-uploads
  env_file:
    - .env
  networks:
    - internal
  depends_on:
    - master-controller-api
```

### Standalone

```bash
cd challenge-uploads
pip install -r requirements.txt
python src/main.py          # Continuous mode (Loop)
python src/main.py once     # One-time run (for testing)
```

## Frequency and Horizon

- Frequency: Extracted from the `frequency` field of the challenge round (ISO 8601 duration, e.g., `PT15M`, `PT1H`, `P1D`)
- Horizon: Extracted from the `horizon` field of the challenge round (ISO 8601 duration, e.g., `PT30M`, `P1D`, `P3D`)
- The horizon is divided by the frequency to calculate the number of forecast steps
- Both ISO 8601 durations and human-readable formats (e.g., "15 minutes") are supported

## Processed Challenges

The service remembers already processed challenges (in memory) and skips them on subsequent checks. On service restart, all active registrations are re-processed.

## Logging

- `INFO`: Shows challenge processing and upload status
- `DEBUG`: Detailed HTTP requests and data processing
- `WARNING`: Issues processing individual series
- `ERROR`: Critical errors in API calls or predictions

## Example Output

```
2026-02-03 14:52:19 [INFO] Challenge Upload Service started
2026-02-03 14:52:19 [INFO] API Base URL: http://your-api-url:8458/
2026-02-03 14:52:19 [INFO] Master Controller URL: http://master-controller-api:8000
2026-02-03 14:52:19 [INFO] Check Interval: 60s
2026-02-03 14:52:19 [INFO] Model matched: Container 'naive-forecast' -> API Name 'Statistical/Naive'
2026-02-03 14:52:19 [INFO] Active models: 1
2026-02-03 14:52:19 [INFO]   - naive-forecast -> Statistical/Naive
2026-02-03 14:52:19 [INFO] Found challenges: 3
2026-02-03 14:52:19 [INFO] Processing challenge round 12098: smard_dam_challenge_24h_15min
2026-02-03 14:52:19 [INFO]   Frequency: PT15M -> 0:15:00
2026-02-03 14:52:19 [INFO]   Horizon: P1D -> 96 steps
2026-02-03 14:52:20 [INFO]   15 series found
2026-02-03 14:52:20 [INFO]   Creating predictions with container naive-forecast for model Statistical/Naive
2026-02-03 14:52:22 [INFO] ✓ Upload successful for round 12098, model Statistical/Naive: 15 series
2026-02-03 14:52:25 [INFO] Waiting 60s for next check...
```
