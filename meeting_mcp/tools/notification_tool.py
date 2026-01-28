import asyncio
from typing import Dict, Any

from meeting_mcp.core.mcp import MCPTool, MCPToolType
from meeting_mcp.agents.notification_agent import NotificationAgent


class NotificationTool(MCPTool):
    def __init__(self):
        super().__init__(
            tool_id="notification",
            tool_type=MCPToolType.NOTIFICATION,
            name="Notification Tool",
            description="Send meeting summary/risks/tasks to external notification channels.",
            api_endpoint="/mcp/notify",
            auth_required=False,
            parameters={"meeting_id": "str", "summary": "dict", "tasks": "list", "risks": "list"}
        )
        self._agent = NotificationAgent()

    async def execute(self, params: Dict[str, Any] = None) -> Dict[str, Any]:
        params = params or {}
        meeting_id = params.get("meeting_id", "ui_session")
        summary = params.get("summary", {})
        tasks = params.get("tasks", [])
        risks = params.get("risks", [])

        loop = asyncio.get_running_loop()
        try:
            res = await loop.run_in_executor(None, self._agent.notify, meeting_id, summary, tasks, risks)
            return {"status": "success", "notified": bool(res)}
        except Exception as e:
            return {"status": "error", "message": str(e)}


__all__ = ["NotificationTool"]
