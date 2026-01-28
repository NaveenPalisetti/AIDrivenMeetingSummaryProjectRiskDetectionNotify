import os
import json
from typing import List, Dict, Any

try:
    from jira import JIRA
except Exception:
    JIRA = None


def create_jira_issues(action_items: List[Dict[str, Any]], user: str = None, date: str = None) -> Dict[str, Any]:
    """Create Jira issues from a list of action items.

    This is a lightweight implementation that attempts to read Jira
    credentials from environment variables (`JIRA_URL`, `JIRA_USER`,
    `JIRA_TOKEN`, `JIRA_PROJECT`) or from `meeting_mcp/config/credentials.json`.
    If credentials or the `jira` package are missing, the function returns
    a result describing the skipped operations.
    """
    # Load credentials from meeting_mcp/config/credentials.json if present
    cred_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "config", "credentials.json"))
    creds = {}
    try:
        if os.path.exists(cred_path):
            with open(cred_path, "r", encoding="utf-8") as fh:
                creds = json.load(fh) or {}
    except Exception:
        creds = {}

    jira_cfg = creds.get("jira", {})
    JIRA_URL = os.environ.get("JIRA_URL") or jira_cfg.get("base_url")
    JIRA_USER = os.environ.get("JIRA_USER") or jira_cfg.get("user")
    JIRA_TOKEN = os.environ.get("JIRA_TOKEN") or jira_cfg.get("token")
    JIRA_PROJECT = os.environ.get("JIRA_PROJECT") or jira_cfg.get("project") or "PROJ"

    created = []
    if not JIRA or not JIRA_URL or not JIRA_USER or not JIRA_TOKEN:
        # Return informative result when Jira can't be used
        for item in action_items:
            title = item.get("summary") or item.get("title") or str(item)
            created.append({
                "title": title,
                "owner": item.get("owner"),
                "due": item.get("due"),
                "jira_issue_key": None,
                "status": "skipped",
                "reason": "jira package or credentials missing"
            })
        return {"status": "skipped", "created_tasks": created}

    try:
        jira_client = JIRA(server=JIRA_URL, basic_auth=(JIRA_USER, JIRA_TOKEN))
    except Exception as e:
        for item in action_items:
            title = item.get("summary") or item.get("title") or str(item)
            created.append({
                "title": title,
                "owner": item.get("owner"),
                "due": item.get("due"),
                "jira_issue_key": None,
                "status": "error",
                "reason": str(e)
            })
        return {"status": "error", "created_tasks": created}

    for item in action_items:
        title = item.get("summary") or item.get("title") or str(item)
        owner = item.get("owner")
        due = item.get("due")
        issue_fields = {
            "project": {"key": JIRA_PROJECT},
            "summary": title.replace("\n", " "),
            "description": f"Created from meeting. Owner: {owner or 'Unassigned'}\nDue: {due or 'Unspecified'}",
            "issuetype": {"name": "Task"}
        }
        try:
            issue = jira_client.create_issue(fields=issue_fields)
            created.append({
                "title": title,
                "owner": owner,
                "due": due,
                "jira_issue_key": getattr(issue, 'key', None),
                "status": "created"
            })
        except Exception as e:
            created.append({
                "title": title,
                "owner": owner,
                "due": due,
                "jira_issue_key": None,
                "status": "error",
                "reason": str(e)
            })

    return {"status": "success", "created_tasks": created}


__all__ = ["create_jira_issues"]
