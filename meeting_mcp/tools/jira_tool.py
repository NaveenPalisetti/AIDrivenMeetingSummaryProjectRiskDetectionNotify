import asyncio
import uuid
from typing import Dict, Any, List

from meeting_mcp.core.mcp import MCPTool, MCPToolType
from meeting_mcp.agents.jira_agent import JiraAgent
from meeting_mcp.protocols.a2a import A2AMessage, PartType


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
            # Build A2A message for Jira agent with a single JSON part
            msg = A2AMessage(message_id=str(uuid.uuid4()), role="client")
            msg.add_json_part({"action_items": action_items, "user": user, "date": date})
            # Call the agent handler in a thread pool
            result_msg = await loop.run_in_executor(None, JiraAgent.handle_create_jira_message, msg)
            # Unwrap JSON part from response
            for part in result_msg.parts:
                if getattr(part, "content_type", None) == PartType.JSON:
                    return {"status": "success", "results": part.content}
            return {"status": "error", "message": "No JSON part in agent response"}
        except Exception as e:
            return {"status": "error", "message": str(e)}


__all__ = ["JiraTool"]
