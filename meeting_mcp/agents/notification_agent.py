import os
import json
from datetime import datetime
try:
    import requests
except Exception:
    requests = None


class NotificationAgent:
    def __init__(self):
        self.slack_webhook = os.environ.get('SLACK_WEBHOOK_URL')

    def notify(self, meeting_id: str, summary: dict, tasks: list, risks: list):
        payload = {
            'meeting_id': meeting_id,
            'summary': summary.get('summary_text') if isinstance(summary, dict) else str(summary),
            'num_tasks': len(tasks) if isinstance(tasks, list) else 0,
            'risks': risks,
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }
        print('=== Notification ===')
        print(json.dumps(payload, indent=2))
        if self.slack_webhook and requests:
            print('Sending Slack notification...')
            try:
                requests.post(self.slack_webhook, json={'text': f"Meeting {meeting_id} summary: {payload['summary']}"})
            except Exception as e:
                print('Slack notify failed:', e)
        return True


__all__ = ["NotificationAgent"]
