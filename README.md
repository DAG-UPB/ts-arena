# TS-Arena: A Pre-registered Live-Data Forecasting Platform 🏟️

Time Series Foundation Models (TSFMs) represent a significant advancement in forecasting capabilities. However, the rapid scaling of these models triggers an evaluation crisis characterized by information leakage and performance reporting issues. Traditional benchmarks are often compromised because TSFMs may inadvertently train on datasets later used for evaluation.

To address these challenges, we introduce **TS-Arena**, a platform for live-data forecasting. The platform reframes the test set as the yet-unseen future, ensuring that evaluation data does not exist at the time of model prediction.

## The Concept of Pre-registration 📝

The core of our methodology is the pre-registration of forecasts. This mechanism requires that a prediction is irrevocably committed at a specific time point  before the ground truth observations manifest. By enforcing this strictly causal timeline, we mitigate two primary forms of information leakage:

* 
**Test Set Contamination**: This occurs when benchmark data is exposed to a model during its pre-training phase. Since our platform uses real-time future data, the target values cannot be part of any training corpus.


* 
**Global Pattern Memorization**: Models can exploit shared global shocks, such as economic crises, that influence many series simultaneously. A global time-split at  ensures models rely on learned dynamics rather than recognizing events they have already seen in other series during training.



## Live Challenges and Visualization 🌐

You can view the rolling leaderboards and active challenges live on Huggingface:
👉 **[TS-Arena on Huggingface](https://huggingface.co/spaces/DAG-UPB/TS-Arena)** 

---

## System Architecture 🏗️

The TS-Arena ecosystem is distributed across three specialized repositories to manage data, models, and user interaction.

### 1. TS-Arena Backend

The [Backend Infrastructure](https://github.com/DAG-UPB/ts-arena-backend) powers the platform by orchestrating challenges and managing data provenance. It consists of several microservices:

* **Data Portal**: Responsible for fetching ground truth data from external providers like the U.S. Energy Information Administration (EIA) and **SMARD** (Bundesnetzagentur).


* 
**API Portal**: Handles model registration, accepts incoming forecasts, and manages the evaluation process.


* **Dashboard API**: Serves the frontend by retrieving statistics and leaderboard data.

### 2. TS-Arena Models

The [Models Repository](https://github.com/DAG-UPB/ts-arena-models) contains the implementation of various state-of-the-art forecasting models. These models serve as baseline participants in the challenges:

* 
**Foundation Models**: Includes Chronos, TimesFM, Moirai, MOMENT, and Time-MoE.


* 
**Standard Baselines**: Includes statistical methods and deep learning models like NHITS or PatchTST.
The repository provides a containerized environment to ensure context parity and full reproducibility across all implemented models.



### 3. TS-Arena Frontend

The [Frontend Dashboard](https://github.com/DAG-UPB/ts-arena-frontend) is built with Streamlit to provide an interactive interface for the benchmark. It allows users to:

* Filter model rankings based on performance metrics like MASE.


* Visualize active and completed challenges using interactive Plotly charts.


* Access information on how to participate and register new models.



## Participation 🤝

The platform is designed to be inclusive for both academic and industrial researchers. Participants can join through containerized inference for maximum rigor or the **Bring Your Own Prediction (BYOP)** mode for proprietary models.

---

## Quick Start: Participate with Your Own Model 🚀

This repository provides everything you need to participate in TS-Arena challenges. The system automatically polls for active challenges, generates forecasts using your model, and uploads them to the API.

### Prerequisites

- Docker & Docker Compose
- API credentials from the TS-Arena platform (API URL + API Key)

### Step 1: Configure Credentials

Create/edit the `.env` file in the project root:

```bash
# TS-Arena API Connection
API_BASE_URL=https://your-api-portal-url.com
API_UPLOAD_KEY=your-api-key-here

# Local settings (usually no changes needed)
CHECK_INTERVAL=60
REQUEST_TIMEOUT=600
LOG_LEVEL=INFO
```

### Step 2: Register Your Model

```bash
cd challenge-uploads/src
python register_models.py --check   # Test API connection
python register_models.py           # Register models from config.json
```

### Step 3: Start the System

```bash
docker compose up -d
```

That's it! The system will now:
1. ✅ Poll for active challenges every 60 seconds
2. ✅ Download context data (historical time series)
3. ✅ Generate forecasts using your model
4. ✅ Upload predictions to the API

### View Logs

```bash
docker compose logs -f challenge-uploads   # See challenge processing
docker compose logs -f naive-forecast      # See model predictions
```

---

## Adding Your Own Model 🔧

The naive forecast model serves as a template. To add your own model:

### 1. Create Your Model Directory

```
model-services/
└── your_model/
    ├── Dockerfile
    ├── requirements.txt
    └── app/
        ├── __init__.py
        ├── main.py      # FastAPI endpoint (copy from example_naive)
        └── model.py     # YOUR PREDICTION LOGIC HERE
```

### 2. Implement the `predict` Method

Edit `model.py` to implement the necessary methods for the point forecast and optional quantiles:

```python
class YourModel:
    def __init__(self):
        # Load your model weights, initialize, etc.
        pass
    
    def predict(
        self,
        history: list,      # Historical data points
        horizon: int,       # Number of steps to forecast
        freq: str,          # Frequency (e.g., "h" for hourly)
        quantile_levels: list  # [0.1, 0.2, ..., 0.9]
    ) -> dict:
        """
        Args:
            history: List of dicts with {"ts": timestamp, "value": float}
                     OR list of lists for batch prediction
            horizon: Number of future steps to predict
            freq: Time frequency string
            quantile_levels: Quantiles to predict, if applicable, otherwise just return an empty dict
            
        Returns:
            {
                "forecasts": [1.2, 1.3, 1.4, ...],  # Point forecasts
                "quantiles": {
                    "0.1": [1.0, 1.1, ...],
                    "0.5": [1.2, 1.3, ...],
                    "0.9": [1.4, 1.5, ...]
                }
            }
        """
        # YOUR MODEL LOGIC HERE
        forecasts = your_model.forecast(history, horizon)
        return {"forecasts": forecasts, "quantiles": {...}}
```

### 3. Create Compose File

Create `compose/your_model.yml`:

```yaml
services:
  your-model:
    extends:
      file: base.yml
      service: gpu-model-base  # or cpu-model-base
    container_name: your-model
    build:
      context: ../model-services/your_model
      dockerfile: Dockerfile
    ports:
      - "8458:8000"
    environment:
      - YOUR_MODEL_PARAM=value
```

### 4. Add to docker-compose.yml

```yaml
include:
  - compose/example_naive.yml
  - compose/your_model.yml  # Add this line
```

### 5. Register in config.json

Add your model to `challenge-uploads/src/config.json`:

```json
{
    "your-model": {
        "name": "your-org/your-model-name",
        "model_type": "TSFM",
        "model_family": "transformer",
        "model_size": 100,
        "hosting": "self-hosted",
        "architecture": "encoder-decoder",
        "pretraining_data": "Your dataset",
        "publishing_date": "2026-01-01",
        "parameters": {}
    }
}
```

### 6. Register and Start

```bash
# Register your new model with the API
cd challenge-uploads/src
python register_models.py

# Start all services
cd ../..
docker compose up -d --build
```