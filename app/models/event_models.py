from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class AnomalyEvent(BaseModel):
    event_id: str
    timestamp: datetime

    source: str  # ex: "server-1", "k8s-pod"
    metric_name: str  # ex: "cpu_usage"
    metric_value: float
    threshold: float

    anomaly_score: float
    severity: str  # INFO / WARNING / CRITICAL

    message: Optional[str] = None

class RecoveryResult(BaseModel):
    event_id: str
    action: str  # ex: "restart_service", "scale_up"
    status: str  # SUCCESS / FAILED
    message: Optional[str] = None
    timestamp: datetime


class DLQEvent(BaseModel):
    original_event: AnomalyEvent
    error_message: str
    failed_at: datetime