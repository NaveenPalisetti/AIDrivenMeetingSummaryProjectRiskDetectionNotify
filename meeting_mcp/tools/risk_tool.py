import asyncio
from typing import Dict, Any

from meeting_mcp.core.mcp import MCPTool, MCPToolType
from meeting_mcp.agents.risk_detection_agent import RiskDetectionAgent


class RiskTool(MCPTool):
    def __init__(self):
        super().__init__(
            tool_id="risk",
            tool_type=MCPToolType.RISK_DETECTION,
            name="Risk Detection Tool",
            description="Detect risks from meeting summary and tasks.",
            api_endpoint="/mcp/risk",
            auth_required=False,
            parameters={"meeting_id": "str", "summary": "dict", "tasks": "list"}
        )
        self._agent = RiskDetectionAgent()

    async def execute(self, params: Dict[str, Any] = None) -> Dict[str, Any]:
        params = params or {}
        meeting_id = params.get("meeting_id", "ui_session")
        summary = params.get("summary", {})
        tasks = params.get("tasks", [])
        progress = params.get("progress", {})

        loop = asyncio.get_running_loop()
        try:
            # Run summary-based detection in executor to avoid blocking
            summary_risks = await loop.run_in_executor(None, self._agent.detect, meeting_id, summary, tasks, progress)

            # Determine whether to include Jira-based risks. If param is not provided,
            # default to including Jira results when a Jira client is configured.
            include_jira_param = params.get("include_jira", None)
            include_jira = include_jira_param if include_jira_param is not None else bool(self._agent.jira)

            jira_risks = []
            if include_jira and self._agent.jira:
                # detect_jira_risks is safe to call without args (uses defaults)
                jira_risks = await loop.run_in_executor(None, self._agent.detect_jira_risks)

            merged = (summary_risks or []) + (jira_risks or [])

            return {
                "status": "success",
                "risks": merged,
                "summary_risks": summary_risks,
                "jira_risks": jira_risks,
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}


__all__ = ["RiskTool"]
