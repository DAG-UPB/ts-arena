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
        """Compute naive quantile forecasts from the spread of the series' own changes.

        Keys are the platform's canonical form, `q_0.1` ... `q_0.9`. The API also accepts
        bare `"0.1"` keys and canonicalises them, but anything outside those two forms —
        `"0.10"`, `"p10"`, `"q10"` — is silently DROPPED from your submission. Emit the
        canonical form and there is nothing to get wrong.

        Deterministic: the band comes from the empirical quantiles of the series' first
        differences. The previous version drew `np.random.standard_normal(10000)` per call
        and took `abs()` of a percentile of it, so identical input produced a different
        band every run and the result was an awkward restatement of `norm.ppf`.
        """
        levels = list(quantile_levels)
        if len(series) < 2:
            # No observed variation to draw a band from. A flat band is still valid,
            # monotone and non-crossing; it just claims no uncertainty.
            return {f"q_{q}": point_forecast for q in levels}

        diffs = np.diff(np.asarray(series, dtype=float))

        quantiles = {}
        for q in levels:
            quantiles[f"q_{q}"] = point_forecast + float(np.quantile(diffs, q))

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