from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Union, Dict, Optional
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from dateutil import parser as date_parser
from .model import NaiveForecastModel

class HistoryItem(BaseModel):
    ts: str
    value: float

class PredictionRequest(BaseModel):
    history: Union[List[List[HistoryItem]], List[HistoryItem]]
    horizon: int
    freq: Optional[str] = "h"

class ForecastItem(BaseModel):
    ts: str
    value: float
    probabilistic_values: Dict[str, float] = {}

class PredictionResponse(BaseModel):
    prediction: Union[List[ForecastItem], List[List[ForecastItem]]]


def parse_timestamp(ts_str: str) -> datetime:
    """Parse timestamp string handling various formats."""
    return date_parser.parse(ts_str)


def generate_future_timestamps(last_timestamp: datetime, horizon: int, freq: str) -> List[str]:
    """Generate future timestamps based on the last known timestamp"""
    timestamps = []
    for i in range(1, horizon + 1):
        if freq == "h":
            new_ts = last_timestamp + timedelta(hours=i)
        elif freq == "15min" or freq == "15T":
            new_ts = last_timestamp + timedelta(minutes=15 * i)
        elif freq == "30min" or freq == "30T":
            new_ts = last_timestamp + timedelta(minutes=30 * i)
        elif freq == "d" or freq == "D":
            new_ts = last_timestamp + timedelta(days=i)
        elif freq == "w" or freq == "W":
            new_ts = last_timestamp + timedelta(weeks=i)
        elif freq == "m" or freq == "M":
            new_ts = last_timestamp + relativedelta(months=i)
        else:
            new_ts = last_timestamp + timedelta(hours=i)
        timestamps.append(new_ts.isoformat())
    return timestamps


def create_forecast_items(
    timestamps: List[str], 
    values: List[float], 
    quantiles_dict: Dict[str, List[float]] = None
) -> List[ForecastItem]:
    """Create ForecastItem objects from timestamps, values, and quantiles."""
    items = []
    for i, (ts, val) in enumerate(zip(timestamps, values)):
        prob_values = {}
        if quantiles_dict:
            for q_level, q_values in quantiles_dict.items():
                prob_values[q_level] = q_values[i] if i < len(q_values) else q_values[-1]
        items.append(ForecastItem(ts=ts, value=val, probabilistic_values=prob_values))
    return items


app = FastAPI()
model = NaiveForecastModel()


@app.post("/predict", response_model=PredictionResponse)
def predict(request: PredictionRequest):
    try:
        # Check if batch or single series
        is_batch = isinstance(request.history[0], list)
        
        if is_batch:
            # Batch prediction
            history_dicts = [
                [{"ts": item.ts, "value": item.value} for item in series]
                for series in request.history
            ]
            
            result = model.predict(
                history=history_dicts,
                horizon=request.horizon,
                freq=request.freq
            )
            
            all_predictions = []
            for idx, series in enumerate(request.history):
                last_ts = parse_timestamp(series[-1].ts)
                future_timestamps = generate_future_timestamps(last_ts, request.horizon, request.freq)
                forecasts = result["forecasts"][idx]
                quantiles = result["quantiles"][idx] if result.get("quantiles") else None
                forecast_items = create_forecast_items(future_timestamps, forecasts, quantiles)
                all_predictions.append(forecast_items)
            
            return PredictionResponse(prediction=all_predictions)
        else:
            # Single series prediction
            history_dicts = [{"ts": item.ts, "value": item.value} for item in request.history]
            
            result = model.predict(
                history=history_dicts,
                horizon=request.horizon,
                freq=request.freq
            )
            
            last_ts = parse_timestamp(request.history[-1].ts)
            future_timestamps = generate_future_timestamps(last_ts, request.horizon, request.freq)
            forecasts = result["forecasts"]
            quantiles = result.get("quantiles")
            forecast_items = create_forecast_items(future_timestamps, forecasts, quantiles)
            
            return PredictionResponse(prediction=forecast_items)
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
def health():
    return {"status": "healthy", "model": "naive-forecast"}