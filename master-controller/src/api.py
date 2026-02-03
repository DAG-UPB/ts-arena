import os
import json
import logging
import math
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional, Union, Dict
from worker import Worker
from config import Config

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

history_example = [
    {"ts": "2026-01-01T00:00:00Z", "value": 10.0},
    {"ts": "2026-01-01T01:00:00Z", "value": 11.5},
    {"ts": "2026-01-01T02:00:00Z", "value": 12.8},
    {"ts": "2026-01-01T03:00:00Z", "value": 14.2},
    {"ts": "2026-01-01T04:00:00Z", "value": 15.1},
    {"ts": "2026-01-01T05:00:00Z", "value": 14.9},
    {"ts": "2026-01-01T06:00:00Z", "value": 16.5},
    {"ts": "2026-01-01T07:00:00Z", "value": 18.2},
    {"ts": "2026-01-01T08:00:00Z", "value": 19.5},
    {"ts": "2026-01-01T09:00:00Z", "value": 21.0},
    {"ts": "2026-01-01T10:00:00Z", "value": 22.4},
    {"ts": "2026-01-01T11:00:00Z", "value": 21.8},
    {"ts": "2026-01-01T12:00:00Z", "value": 20.5},
    {"ts": "2026-01-01T13:00:00Z", "value": 19.2},
    {"ts": "2026-01-01T14:00:00Z", "value": 18.0},
    {"ts": "2026-01-01T15:00:00Z", "value": 17.5},
    {"ts": "2026-01-01T16:00:00Z", "value": 16.8},
    {"ts": "2026-01-01T17:00:00Z", "value": 15.5},
    {"ts": "2026-01-01T18:00:00Z", "value": 14.2},
    {"ts": "2026-01-01T19:00:00Z", "value": 13.0},
    {"ts": "2026-01-01T20:00:00Z", "value": 12.5},
    {"ts": "2026-01-01T21:00:00Z", "value": 11.8},
    {"ts": "2026-01-01T22:00:00Z", "value": 11.0},
    {"ts": "2026-01-01T23:00:00Z", "value": 10.5}
  ]
class HistoryItem(BaseModel):
    ts: str
    value: float


app = FastAPI()

class PredictionRequest(BaseModel):
    model_name: str = Field(examples=["timesfm"])
    history: Union[List[List[HistoryItem]], List[HistoryItem]] = Field(examples=[history_example])
    horizon: int = Field(examples=[2])
    freq: Optional[str] = Field(default="h", examples=["h"])

class ForecastItem(BaseModel):
    ts: str
    value: float
    probabilistic_values: Dict[str, float] = {}

class PredictionResponse(BaseModel):
    model_name: str
    prediction: Union[List[ForecastItem], List[List[ForecastItem]]]

@app.post("/predict", response_model=PredictionResponse)
async def predict_batch(request: PredictionRequest):
    """
    Takes a list of time series histories and performs a prediction for each with the specified model.
    """
    logging.info(f"Request for batch prediction with model '{request.model_name}' received.")


    predictions = []

    try:
        with Worker(
            service_name= "ts-models-" + request.model_name + "-1",
            base_url=f"http://{request.model_name}",
        ) as worker:
            # Convert Pydantic models to dicts for JSON serialization
            history_data = request.history
            if isinstance(history_data, list) and len(history_data) > 0:
                if isinstance(history_data[0], HistoryItem):
                     # Single series case: List[HistoryItem] -> convert to list of dicts
                    history_data = [item.model_dump() for item in history_data]
                elif isinstance(history_data[0], list):
                     # Batch case: List[List[HistoryItem]] -> convert to list of list of dicts
                    history_data = [[item.model_dump() for item in series] for series in history_data]

            prediction_data = {
                "history": history_data, 
                "horizon": request.horizon,
                "freq": request.freq
            }
            prediction_result = worker.predict(data=prediction_data)

            if prediction_result and "prediction" in prediction_result:
                predictions = prediction_result["prediction"]
            else:
                logging.error(f"No valid prediction received from {request.model_name}.")
                raise HTTPException(status_code=500, detail=f"No valid prediction received from {request.model_name}.")

    except Exception as e:
        logging.error(f"An error occurred while processing {request.model_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    logging.info(f"Batch prediction for model '{request.model_name}' completed.")
    return PredictionResponse(model_name=request.model_name, prediction=predictions)

@app.get("/health")
def health_check():
    return {"status": "ok"}