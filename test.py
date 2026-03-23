from app.services.slack_notifier import send_slack_alert

send_slack_alert(
    event={
        "metric_name": "cpu_usage",
        "metric_value": 999,
        "threshold": 80,
        "severity": "CRITICAL",
        "message": "Test anomaly"
    },
    score=0.95
)