import asyncio
from typing import Dict, Any, List

from meeting_mcp.core.mcp import MCPTool, MCPToolType
from meeting_mcp.agents.summarization_agent import SummarizationAgent


class SummarizationTool(MCPTool):
    def __init__(self):
        super().__init__(
            tool_id="summarization",
            tool_type=MCPToolType.SUMMARIZATION,
            name="Summarization Tool",
            description="Summarize processed transcript chunks using BART or Mistral.",
            api_endpoint="/mcp/summarize",
            auth_required=False,
            parameters={"processed_transcripts": "list[str]", "mode": "str"}
        )
        self._agent = SummarizationAgent()

    async def execute(self, params: Dict[str, Any] = None) -> Dict[str, Any]:
        params = params or {}
        processed: List[str] = params.get("processed_transcripts") or params.get("processed") or []
        mode = params.get("mode") or params.get("summarizer") or None
        loop = asyncio.get_running_loop()
        try:
            # Run the agent's summarize_protocol in an executor to avoid blocking
            result = await loop.run_in_executor(None, self._agent.summarize_protocol, processed, mode)
            return {"status": "success", "summary": result}
        except Exception as e:
            return {"status": "error", "message": str(e)}


__all__ = ["SummarizationTool"]
