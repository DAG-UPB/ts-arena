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
API_BASE_URL=http://localhost:8457
API_UPLOAD_KEY=your_api_key_here

# Master Controller (for model inference)
MASTER_CONTROLLER_URL=http://localhost:8456

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

1. **Challenge Polling**: Regularly polls all available challenges via `GET /api/v1/challenge/`
2. **Registration Check**: Checks for each challenge if the current time is within `registration_start` and `registration_end`
3. **Challenge Details**: Fetches challenge details (`GET /api/v1/challenge/{round_id}`) to determine frequency and horizon
4. **Context Data**: Loads historical data via `GET /api/v1/challenge/{round_id}/context-data` with API key
5. **Prediction**: Sends history data to the Master Controller (`POST http://master-controller:8456/predict`) for each configured model
6. **Formatting**: Formats predictions according to API specification with correct timestamps based on frequency
7. **Upload**: Uploads forecasts via `POST /api/v1/forecasts/upload`

**Note**: Uploading forecasts automatically registers your model as a challenge participant. No separate registration step needed per challenge!

## Configuration

### Environment variables in `.env`:

| Variable | Description | Default |
|----------|-------------|---------|
| `API_BASE_URL` | URL of the ts-arena-backend API Portal | `http://localhost:8457` |
| `API_UPLOAD_KEY` | Your API key (linked to your user) | **Required** |
| `MASTER_CONTROLLER_URL` | URL of the Master Controller | `http://localhost:8456` |
| `CHECK_INTERVAL` | Seconds between challenge checks | `60` |
| `REQUEST_TIMEOUT` | HTTP request timeout in seconds | `600` |
| `LOG_LEVEL` | Logging level | `INFO` |

### Model Configuration (config.json)

Add your models to `src/config.json`:

```json
{
  "naive-forecast": {
    "name": "example/naive-forecast",
    "model_type": "Statistical",
    "model_family": "naive",
    "model_size": 0,
    "hosting": "self-hosted",
    "architecture": "naive",
    "pretraining_data": "None (naive baseline)",
    "publishing_date": "2026-01-28",
    "parameters": {}
  }
}
```

The key (e.g., `naive-forecast`) is the container name used for inference.
The `name` field is what gets registered with the API and used in forecast uploads.

## Forecast Upload Format

When uploading forecasts, use this payload format:

```json
{
  "challenge_id": 100,
  "model_name": "example/naive-forecast",
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

- Frequency: Extracted from `preparation_params["frequency"]` of the challenge (e.g. "15 minutes", "1 hour")
- Horizon: Extracted from the `horizon` field of the challenge (e.g. "PT1H" for 1 hour in ISO 8601 format)
- Forecast timestamps are automatically calculated based on frequency

## Processed Challenges

The service remembers already processed challenges (in memory) and skips them on subsequent checks. On service restart, all active registrations are re-processed.

## Logging

- `INFO`: Shows challenge processing and upload status
- `DEBUG`: Detailed HTTP requests and data processing
- `WARNING`: Issues processing individual series
- `ERROR`: Critical errors in API calls or predictions

## Example Output

```
2026-01-28 10:00:00 [INFO] Challenge Upload Service started
2026-01-28 10:00:00 [INFO] API Base URL: http://localhost:8457
2026-01-28 10:00:00 [INFO] Master Controller URL: http://localhost:8456
2026-01-28 10:00:05 [INFO] Found challenges: 3
2026-01-28 10:00:05 [INFO] Processing challenge 42: Energy Forecast Challenge
2026-01-28 10:00:05 [INFO]   Frequency: 15 minutes -> 0:15:00
2026-01-28 10:00:05 [INFO]   Horizon: PT1H -> 4 steps
2026-01-28 10:00:05 [INFO]   3 series found
2026-01-28 10:00:05 [INFO]   Creating predictions with container naive-forecast
2026-01-28 10:00:15 [INFO] ✓ Upload successful for challenge 42: 3 series
```
