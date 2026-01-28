import os
import json
import uuid
from typing import List, Dict, Any

try:
    from jira import JIRA
except Exception:
    JIRA = None


class RiskDetectionAgent:
    """Detect simple risks from meeting summary, tasks, and optionally Jira.

    Methods
    - detect: lightweight heuristic scan of summary/tasks
    - detect_jira_risks: query Jira for overdue, unassigned, blocked, stale, and high-priority issues
    """

    def __init__(self):
        # Initialize Jira client if credentials found
        self.jira = None
        self.jira_project = os.environ.get("JIRA_PROJECT")
        cred_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'credentials.json')
        try:
            if os.path.exists(cred_path):
                with open(cred_path, 'r', encoding='utf-8') as fh:
                    creds = json.load(fh) or {}
                    jira_cfg = creds.get('jira', {})
                    jira_url = os.environ.get('JIRA_URL') or jira_cfg.get('base_url')
                    jira_user = os.environ.get('JIRA_USER') or jira_cfg.get('user')
                    jira_token = os.environ.get('JIRA_TOKEN') or jira_cfg.get('token')
                    self.jira_project = os.environ.get('JIRA_PROJECT') or jira_cfg.get('project') or self.jira_project
            else:
                jira_url = os.environ.get('JIRA_URL')
                jira_user = os.environ.get('JIRA_USER')
                jira_token = os.environ.get('JIRA_TOKEN')
        except Exception:
            jira_url = os.environ.get('JIRA_URL')
            jira_user = os.environ.get('JIRA_USER')
            jira_token = os.environ.get('JIRA_TOKEN')

        if JIRA and jira_url and jira_user and jira_token:
            try:
                self.jira = JIRA(server=jira_url, basic_auth=(jira_user, jira_token))
            except Exception:
                self.jira = None

    def _gen_id(self, prefix: str = "risk") -> str:
        return f"{prefix}_{uuid.uuid4().hex[:8]}"

    def detect(self, meeting_id: str, summary: Dict[str, Any], tasks: List[Dict[str, Any]], progress: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Lightweight heuristic detection from summary text and tasks."""
        risks: List[Dict[str, Any]] = []
        blockers = []
        try:
            if isinstance(summary, dict):
                blockers = summary.get("blockers", []) or []
                summary_text = summary.get("summary_text", "") or ""
            else:
                summary_text = str(summary)
        except Exception:
            summary_text = ""

        st = (summary_text or "").lower()

        # Blockers mentioned explicitly
        if blockers:
            for b in blockers:
                risks.append({
                    "id": self._gen_id(),
                    "meeting_id": meeting_id,
                    "description": str(b),
                    "severity": "high",
                    "source": "summary"
                })

        # Heuristic keyword scan for common risk indicators
        risk_terms = ["delay", "delayed", "blocked", "blocking", "pending", "cannot", "error", "risk", "concern", "issue"]
        if any(term in st for term in risk_terms):
            risks.append({
                "id": self._gen_id(),
                "meeting_id": meeting_id,
                "description": "Detected terms indicating potential delay, blockage or concern.",
                "severity": "medium",
                "source": "summary"
            })

        # Task-based heuristics (jira-level risk)
        try:
            if isinstance(tasks, list) and len(tasks) > 5:
                risks.append({
                    "id": self._gen_id(),
                    "meeting_id": meeting_id,
                    "description": "Many tasks created in a single meeting; review capacity and scope.",
                    "severity": "medium",
                    "source": "tasks"
                })
        except Exception:
            pass

        # If nothing found, return a low-severity placeholder
        if not risks:
            risks.append({
                "id": self._gen_id(),
                "meeting_id": meeting_id,
                "description": "No immediate risks detected.",
                "severity": "low",
                "source": "analysis"
            })

        return risks

    def detect_jira_risks(self, days_overdue: int = 0, days_stale: int = 7) -> List[Dict[str, Any]]:
        """Query Jira for common risk signals (overdue, unassigned, blocked, stale, high priority).

        Returns a list of risk dicts. If Jira is not configured, returns an empty list.
        """
        risks: List[Dict[str, Any]] = []
        if not self.jira:
            return risks

        from datetime import datetime, timedelta
        now = datetime.utcnow()

        # 1. Overdue tasks
        try:
            jql_overdue = f'project={self.jira_project} AND duedate <= now() AND statusCategory != Done'
            for issue in self.jira.search_issues(jql_overdue):
                risks.append({
                    'type': 'overdue',
                    'key': getattr(issue, 'key', None),
                    'summary': getattr(issue.fields, 'summary', None),
                    'due_date': getattr(issue.fields, 'duedate', None),
                    'description': 'Task is overdue.',
                    'source': 'jira'
                })
        except Exception:
            pass

        # 2. Unassigned tasks
        try:
            jql_unassigned = f'project={self.jira_project} AND assignee is EMPTY AND statusCategory != Done'
            for issue in self.jira.search_issues(jql_unassigned):
                risks.append({
                    'type': 'unassigned',
                    'key': getattr(issue, 'key', None),
                    'summary': getattr(issue.fields, 'summary', None),
                    'description': 'Task is unassigned.',
                    'source': 'jira'
                })
        except Exception:
            pass

        # 3. Blocked/flagged issues
        try:
            jql_blocked = f'project={self.jira_project} AND (flagged = Impediment OR status = Blocked) AND statusCategory != Done'
            for issue in self.jira.search_issues(jql_blocked):
                risks.append({
                    'type': 'blocked',
                    'key': getattr(issue, 'key', None),
                    'summary': getattr(issue.fields, 'summary', None),
                    'description': 'Task is blocked or flagged.',
                    'source': 'jira'
                })
        except Exception:
            pass

        # 4. No due date
        try:
            jql_nodue = f'project={self.jira_project} AND duedate is EMPTY AND statusCategory != Done'
            for issue in self.jira.search_issues(jql_nodue):
                risks.append({
                    'type': 'no_due_date',
                    'key': getattr(issue, 'key', None),
                    'summary': getattr(issue.fields, 'summary', None),
                    'description': 'Task has no due date.',
                    'source': 'jira'
                })
        except Exception:
            pass

        # 5. Stale tasks (not updated in days_stale)
        try:
            stale_date = (now - timedelta(days=days_stale)).strftime('%Y-%m-%d')
            jql_stale = f'project={self.jira_project} AND updated <= "{stale_date}" AND statusCategory != Done'
            for issue in self.jira.search_issues(jql_stale):
                risks.append({
                    'type': 'stale',
                    'key': getattr(issue, 'key', None),
                    'summary': getattr(issue.fields, 'summary', None),
                    'last_updated': getattr(issue.fields, 'updated', None),
                    'description': f'Task not updated in {days_stale}+ days.',
                    'source': 'jira'
                })
        except Exception:
            pass

        # 6. High priority unresolved
        try:
            jql_highprio = f'project={self.jira_project} AND priority = Highest AND statusCategory != Done'
            for issue in self.jira.search_issues(jql_highprio):
                risks.append({
                    'type': 'high_priority',
                    'key': getattr(issue, 'key', None),
                    'summary': getattr(issue.fields, 'summary', None),
                    'priority': getattr(issue.fields, 'priority', None),
                    'description': 'High priority task unresolved.',
                    'source': 'jira'
                })
        except Exception:
            pass

        return risks


__all__ = ["RiskDetectionAgent"]
