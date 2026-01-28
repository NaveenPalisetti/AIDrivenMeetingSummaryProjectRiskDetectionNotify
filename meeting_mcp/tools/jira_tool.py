import asyncio
from typing import Dict, Any, List

from meeting_mcp.core.mcp import MCPTool, MCPToolType
from meeting_mcp.agents.jira_agent import create_jira_issues


class JiraTool(MCPTool):
    def __init__(self):
        super().__init__(
            tool_id="jira",
            tool_type=MCPToolType.JIRA,
            name="Jira Tool",
            description="Create Jira issues from action items extracted from meetings.",
            api_endpoint="/mcp/jira",
            auth_required=False,
            parameters={"action_items": "list[dict]", "user": "str", "date": "str"}
        )

    async def execute(self, params: Dict[str, Any] = None) -> Dict[str, Any]:
        params = params or {}
        action_items: List[Dict[str, Any]] = params.get("action_items") or params.get("action_items_list") or []
        user = params.get("user")
        date = params.get("date")
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(None, create_jira_issues, action_items, user, date)
            return {"status": "success", "results": result}
        except Exception as e:
            return {"status": "error", "message": str(e)}


__all__ = ["JiraTool"]
