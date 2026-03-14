import os
from typing import List, Union, Dict, Any
import numpy as np

class NaiveForecastModel:
    def __init__(self) -> None:
        self.strategy = os.environ.get("NAIVE_STRATEGY", "last").lower()

    def _get_naive_value(self, series: List[float]) -> float:
        """Get the naive forecast value based on strategy."""
        if not series:
            return 0.0
        
        if self.strategy == "mean":
            return float(np.mean(series))
        elif self.strategy == "median":
            return float(np.median(series))
        elif self.strategy == "first":
            return float(series[0])
        else:  # default: "last"
            return float(series[-1])
        
    def _compute_quantiles(
        self, 
        series: List[float], 
        point_forecast: float, 
        quantile_levels: List[float] = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
    ) -> Dict[str, float]:
        """Compute naive quantile forecasts based on historical variance."""
        if len(series) < 2:
            return {str(q): point_forecast for q in quantile_levels}
        
        std = float(np.std(series))
        
        quantiles = {}
        for q in quantile_levels:
            z_score = float(np.abs(np.percentile(np.random.standard_normal(10000), q * 100)))
            if q < 0.5:
                quantiles[str(q)] = point_forecast - z_score * std
            elif q > 0.5:
                quantiles[str(q)] = point_forecast + z_score * std
            else:
                quantiles[str(q)] = point_forecast
        
        return quantiles

    def predict(
            self,
            history: Union[List[Dict[str, Any]], List[List[Dict[str, Any]]]],
            horizon: int,
            freq: str = "h",
            quantile_levels: List[float] = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
        ) -> Dict[str, Any]:
        """
        Generate naive forecast predictions.
        
        Returns:
            Dict with 'forecasts' and 'quantiles'
        """
        if not history:
            raise ValueError("History must not be empty.")
        
        # Check if batch (list of lists) or single series
        is_batch = isinstance(history[0], list)
        
        if is_batch:
            all_forecasts = []
            all_quantiles = {}  # Dict with integer keys to match main.py access pattern
            
            for idx, series in enumerate(history):
                values = [float(item.get("value", 0)) for item in series]
                point_forecast = self._get_naive_value(values)
                forecasts = [point_forecast] * horizon
                all_forecasts.append(forecasts)
                
                q_values = self._compute_quantiles(values, point_forecast, quantile_levels)
                all_quantiles[idx] = {k: [v] * horizon for k, v in q_values.items()}
            
            return {"forecasts": all_forecasts, "quantiles": all_quantiles}
        else:
            # Single series
            values = [float(item.get("value", 0)) for item in history]
            point_forecast = self._get_naive_value(values)
            forecasts = [point_forecast] * horizon
            
            q_values = self._compute_quantiles(values, point_forecast, quantile_levels)
            quantiles = {k: [v] * horizon for k, v in q_values.items()}
            
            return {"forecasts": forecasts, "quantiles": quantiles}