from ..protocols.a2a import AgentCard, AgentCapability, A2AMessage, PartType

import os
import json
import uuid
from typing import List, Dict, Any

try:
    from jira import JIRA
except Exception:
    JIRA = None

class JiraAgent:
    AGENT_CARD = AgentCard(
        agent_id="jira_agent",
        name="JiraAgent",
        description="Handles Jira ticket creation and management via A2A protocol.",
        version="1.0",
        capabilities=[
            AgentCapability(
                name="create_jira",
                description="Create Jira issues from action items or user requests."
            ),
        ],
    )

    def __init__(self, mcp_host: object = None):
        self.mcp_host = mcp_host
        self.mcp_session_id = None
        if mcp_host is not None:
            try:
                self.mcp_session_id = mcp_host.create_session(self.AGENT_CARD.agent_id)
            except Exception:
                self.mcp_session_id = None

    @staticmethod
    def handle_create_jira_message(msg: A2AMessage) -> A2AMessage:
        """Handle A2A create_jira messages."""
        # Extract action items from JSON parts (align with calendar agent pattern)
        action_items = None
        user = None
        date = None
        for part in msg.parts:
            if getattr(part, "content_type", None) == PartType.JSON:
                content = getattr(part, "content", None)
                if isinstance(content, dict):
                    # Accept empty lists as valid action_items (don't use `or` which treats [] as falsy)
                    if "action_items" in content:
                        action_items = content["action_items"]
                    elif "items" in content:
                        action_items = content["items"]
                    elif "tasks" in content:
                        action_items = content["tasks"]
                    if "user" in content:
                        user = content.get("user") or content.get("owner")
                    if "date" in content:
                        date = content.get("date")
                    break

        if not action_items:
            # Fallback: aggregate any JSON/text parts into action_items list
            collected = []
            for part in msg.parts:
                cont = getattr(part, "content", None)
                if isinstance(cont, dict):
                    collected.append(cont)
                elif isinstance(cont, str):
                    collected.append({"summary": cont})
            action_items = collected

        # Call the existing Jira creation logic
        result = JiraAgent.create_jira_issues(action_items or [], user=user, date=date)
        resp = A2AMessage(message_id=str(uuid.uuid4()), role="agent")
        resp.add_json_part(result)
        return resp

    @staticmethod
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


__all__ = ["JiraAgent"]
