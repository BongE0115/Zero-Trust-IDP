import logging
import pandas as pd

from merlion.models.anomaly.isolation_forest import IsolationForest, IsolationForestConfig
from merlion.utils import TimeSeries

logger = logging.getLogger(__name__)


class MerlionAnomalyDetector:
    def __init__(self):
        # 🔥 config 필수
        config = IsolationForestConfig()
        self.model = IsolationForest(config)

        self.is_trained = False

    def train(self, time_series_data: list):
        if len(time_series_data) < 5:
            logger.warning("[Merlion] Not enough data to train")
            return

        df = pd.DataFrame(time_series_data)
        df = df.set_index("timestamp")

        ts = TimeSeries.from_pd(df)

        self.model.train(ts)
        self.is_trained = True

        logger.info("[Merlion] Model trained")

    def detect(self, time_series_data: list):
        if not self.is_trained:
            logger.warning("[Merlion] Model not trained")
            return None

        df = pd.DataFrame(time_series_data)
        df = df.set_index("timestamp")

        ts = TimeSeries.from_pd(df)

        scores = self.model.get_anomaly_score(ts)

        latest_score = scores.to_pd().iloc[-1].iloc[0]

        logger.info(f"[Merlion] Anomaly score: {latest_score}")

        return latest_score

    def is_anomaly(self, score: float, threshold: float = 0.55):
        return score > threshold