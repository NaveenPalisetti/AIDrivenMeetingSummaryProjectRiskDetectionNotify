from ..protocols.a2a import AgentCard, AgentCapability, A2AMessage, PartType
import os
import json
from datetime import datetime
try:
    import requests
except Exception:
    requests = None



class NotificationAgent:
    AGENT_CARD = AgentCard(
        agent_id="notification_agent",
        name="NotificationAgent",
        description="Sends meeting summary, tasks, and risks to external notification channels via A2A protocol.",
        version="1.0",
        capabilities=[
            AgentCapability(
                name="notify",
                description="Send meeting summary, tasks, and risks to notification channels."
            ),
        ],
    )

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

    @staticmethod
    def handle_notify_message(msg: A2AMessage) -> A2AMessage:
        """Handle A2A notify messages."""
        meeting_id = None
        summary = None
        tasks = []
        risks = []
        for part in msg.parts:
            ptype = part.get("type")
            if ptype in (PartType.MEETING_ID, "meeting_id"):
                meeting_id = part.get("content")
            elif ptype in (PartType.SUMMARY, "summary"):
                summary = part.get("content")
            elif ptype in (PartType.TASK, PartType.ACTION_ITEM, "task", "action_item"):
                tasks.append(part.get("content"))
            elif ptype in (PartType.RISK, "risk"):
                risks.append(part.get("content"))
        if not meeting_id:
            meeting_id = "unknown"
        if summary is None:
            summary = ""
        agent = NotificationAgent()
        notified = agent.notify(meeting_id, summary, tasks, risks)
        return A2AMessage(
            sender=NotificationAgent.AGENT_CARD.name,
            recipient=msg.sender,
            parts=[
                {
                    "type": PartType.RESULT,
                    "content": {"notified": bool(notified)}
                }
            ]
        )


__all__ = ["NotificationAgent"]
