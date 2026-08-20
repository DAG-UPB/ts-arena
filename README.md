# TS-Arena: A Live Forecast Pre-Registration Platform 🏟️

<div align="center">

[![KDD 2026](https://img.shields.io/badge/KDD_2026-Datasets_%26_Benchmarks-0085CA?logo=acm&logoColor=white)](https://doi.org/10.1145/3770855.3817515)
[![Paper](https://img.shields.io/badge/arXiv-2512.20761-b31b1b?logo=arxiv&logoColor=white)](https://arxiv.org/abs/2512.20761)
[![ICLR TSALM Workshop](https://img.shields.io/badge/ICLR_TSALM_Workshop-OpenReview-blue?logo=openreview&logoColor=white)](https://openreview.net/forum?id=TcKLyWrfZT)
[![Live Arena](https://img.shields.io/badge/TS--Arena-Live_Leaderboard-green?logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCI+PHBhdGggZD0iTTEyIDJMMiA3bDEwIDUgMTAtNS0xMC01ek0yIDE3bDEwIDUgMTAtNS0xMC01ek0yIDEybDEwIDUgMTAtNS0xMC01eiIvPjwvc3ZnPg==)](https://ts-arena.live/)

</div>

Time Series Foundation Models (TSFMs) are transforming the field of forecasting. However, evaluating them on historical data is increasingly difficult due to two distinct forms of information leakage: train-test sample overlaps and temporal overlaps between correlated train and test time series. TS-Arena addresses both by shifting evaluation from the known past to the unknown future.

> **About this repository**: This repo provides a high-level overview of the TS-Arena platform and a minimal example for participating with your own model. The full system is distributed across three specialized repositories — see the [System Architecture](#system-architecture-) section for details and links.

## The Concept of Pre-Registration 📝

The core of our methodology is the **Forecast Pre-Registration Protocol (FPRP)**. This mechanism requires that a prediction is irrevocably committed at a specific point in time *before* the ground-truth observations physically exist. By enforcing this strictly causal timeline, both forms of information leakage are made impossible by design:

- **No train-test sample overlaps**: Since evaluation targets are future data points that do not exist at submission time, they cannot appear in any training corpus.
- **No temporal overlap of correlated series**: The global time split at $t_{now}$ ensures that all correlated series — in training and test sets alike — share the same information horizon, eliminating any indirect look-ahead through cross-series temporal leakage.

Challenges are structured into iterative *rounds*, each consisting of a context window of historical observations, a registration window during which forecasts must be submitted, and a forecast horizon evaluated once the ground truth materializes. This continuous, rolling structure enables fast and reproducible evaluation in the spirit of time-series cross-validation.

## Live Challenges and Leaderboard 🌐

Active challenges and rolling leaderboards are available at:

👉 **[ts-arena.live](https://ts-arena.live/)**

---

## System Architecture 🏗️

TS-Arena is distributed across three specialized repositories that manage data ingestion, model hosting, and user interaction.

### 1. TS-Arena Backend

The [Backend Infrastructure](https://github.com/DAG-UPB/ts-arena-backend) orchestrates challenges and manages data provenance through a modular microservice architecture:

- **Data Portal**: Continuously fetches ground-truth time series from external providers such as SMARD (Bundesnetzagentur), Fingrid, and Gridstatus. Raw data is standardized into a unified schema and stored using a Slowly Changing Dimension Type 2 (SCD2) archiving strategy, allowing full reconstruction of the exact information state available at any historical $t_{now}$.

- **API Portal**: The central orchestration unit for participants. It handles model registration, validates incoming forecast submissions against active registration windows, and triggers evaluation once ground truth becomes available.

- **Dashboard API**: A read-only API that supplies the frontend with live leaderboard data, challenge statuses, and per-series forecast information.

### 2. TS-Arena Models

The [Models Repository](https://github.com/DAG-UPB/ts-arena-models) contains containerized implementations of state-of-the-art forecasting models that serve as reference participants:

- **Foundation Models**: e.g. Chronos, tirex, TimesFM, Moirai or Time-MoE.
- **Statistical Baselines**: naive (seasonal) methods.

All models run in containerized environments to ensure context parity and full reproducibility.

### 3. TS-Arena Frontend

The [Frontend Dashboard](https://github.com/DAG-UPB/ts-arena-frontend) is a Streamlit web application that allows users to:

- Browse and filter model rankings by performance metrics (MASE, ELO with confidence intervals).
- Visualize active and completed challenge rounds through interactive Plotly charts.
- Access participation instructions and model registration details.

---

## Participation 🤝

TS-Arena is designed to be inclusive for both academic and industrial researchers. Participants can join via:

- **Containerized inference**: Full Docker-based submission for maximum rigor and reproducibility.
- **Bring Your Own Prediction (BYOP)**: A lightweight mode for proprietary or closed models where predictions are uploaded directly via the API.

---

## Quick Start: Participate with Your Own Model 🚀

This repository provides everything you need to participate in TS-Arena challenges. The system automatically polls for active challenges, generates forecasts using your model, and uploads them to the API.

### Prerequisites

- Docker & Docker Compose
- API credentials from the TS-Arena platform (API URL + API Key)

### Step 1: Configure Credentials

Create/edit the `.env` file in the `ts-arena-participation_example/` directory:

```bash
# TS-Arena API Connection
API_BASE_URL=http://your-api-portal-url
API_UPLOAD_KEY=your-api-key-here

USER_ID=your-user-id-here

# This is the local service that routes predictions to your model containers
MASTER_CONTROLLER_URL=http://master-controller-api:8000

# Local settings (usually no changes needed)
CHECK_INTERVAL=300
REQUEST_TIMEOUT=600
LOG_LEVEL=INFO
```

### Step 2: Register Your Model

```bash
cd ts-arena-participation_example/challenge-uploads/src
python register_models.py --check   # Test API connection
python register_models.py           # Register models from config.json
```

### Step 3: Start the System

```bash
cd ts-arena-participation_example
docker compose up -d
```

That's it! The system will now:
1. ✅ Poll for active challenges every 5 minutes
2. ✅ Download context data (historical time series)
3. ✅ Generate forecasts using your model
4. ✅ Upload predictions to the API before the registration window closes

### View Logs

```bash
cd ts-arena-participation_example
docker compose logs -f challenge-uploads   # See challenge processing
docker compose logs -f naive-forecast      # See model predictions
```

---

## Adding Your Own Model 🔧

The naive forecast model serves as a template. To add your own model:

### 1. Create Your Model Directory

```
ts-arena-participation_example/model-services/
└── your_model/
    ├── Dockerfile
    ├── requirements.txt
    └── app/
        ├── __init__.py
        ├── main.py      # FastAPI endpoint (copy from example_naive)
        └── model.py     # YOUR PREDICTION LOGIC HERE
```

### 2. Implement the `predict` Method

Edit `model.py` to implement point forecasts and optional quantiles:

```python
class YourModel:
    def __init__(self):
        # Load your model weights, initialize, etc.
        pass

    def predict(
        self,
        history: list,         # Historical data points
        horizon: int,          # Number of steps to forecast
        freq: str,             # Frequency (e.g., "h" for hourly)
        quantile_levels: list  # [0.1, 0.2, ..., 0.9]
    ) -> dict:
        """
        Args:
            history: List of dicts with {"ts": timestamp, "value": float}
                     OR list of lists for batch prediction
            horizon: Number of future steps to predict
            freq: Time frequency string
            quantile_levels: Quantiles to predict; return empty dict if not applicable

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
        forecasts = your_model.forecast(history, horizon)
        return {"forecasts": forecasts, "quantiles": {...}}
```

### 3. Create Compose File

Create `ts-arena-participation_example/compose/your_model.yml`:

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

### 4. Add to ts-arena-participation_example/docker-compose.yml

```yaml
include:
  - compose/example_naive.yml
  - compose/your_model.yml  # Add this line
```

### 5. Register in config.json

Add your model to `ts-arena-participation_example/challenge-uploads/src/config.json`:

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
cd ts-arena-participation_example/challenge-uploads/src
python register_models.py

# Start all services
cd ../../..
cd ts-arena-participation_example
docker compose up -d --build
```

---

## Citation 📖

TS-Arena was published at **KDD '26** (Datasets & Benchmarks Track). If you use TS-Arena
in your research, please cite:

```bibtex
@inproceedings{meyer2026tsarena,
  title     = {TS-Arena -- A Live Forecast Pre-Registration Platform},
  author    = {Meyer, Marcel and Kaltenpoth, Sascha and Albers, Henrik and Zalipski, Kevin and M{\"u}ller, Oliver},
  booktitle = {Proceedings of the 32nd ACM SIGKDD Conference on Knowledge Discovery and Data Mining V.2},
  series    = {KDD '26},
  pages     = {9558--9568},
  year      = {2026},
  publisher = {Association for Computing Machinery},
  doi       = {10.1145/3770855.3817515},
  url       = {https://doi.org/10.1145/3770855.3817515}
}
```

The preprint remains available at [arXiv:2512.20761](https://arxiv.org/abs/2512.20761).
