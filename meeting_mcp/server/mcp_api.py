from typing import Any, Optional, List, Dict
import os

from fastapi import FastAPI, Depends, Header, HTTPException, status
from pydantic import BaseModel

from meeting_mcp.core.mcp import MCPHost
from meeting_mcp.tools.calendar_tool import CalendarTool
from meeting_mcp.tools.transcript_tool import TranscriptTool
from meeting_mcp.tools.summarization_tool import SummarizationTool
from meeting_mcp.tools.jira_tool import JiraTool
from meeting_mcp.tools.risk_tool import RiskTool
from meeting_mcp.agents.orchestrator_agent import OrchestratorAgent

from Log.logger import setup_logging
import logging


app = FastAPI(title="meeting_mcp API")

# configure file logging (creates Log/meeting_mcp.log in repo)
try:
    setup_logging()
    logging.getLogger(__name__).info("File logging enabled")
except Exception:
    logging.getLogger(__name__).exception("Failed to setup file logging")

# Note: CORS middleware removed per request (if needed, re-add carefully)


def verify_api_key(x_api_key: Optional[str] = Header(None)):
    """Simple API key verification dependency.

    For local development you can bypass the check by setting the environment
    variable `DISABLE_API_KEY_CHECK=1`. When bypass is disabled behavior is
    unchanged: if `MCP_API_KEY` is not set the API allows requests; otherwise
    requests must provide `x-api-key` header equal to `MCP_API_KEY`.
    """
    # Explicit bypass for local development/testing
    if os.environ.get("DISABLE_API_KEY_CHECK") == "1":
        return True

    expected = os.environ.get("MCP_API_KEY")
    if expected is None:
        # No API key configured — allow local/dev usage
        return True
    if not x_api_key or x_api_key != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing API key")
    return True

# Create an in-process MCP host and register the Calendar tool
mcp_host = MCPHost()
calendar_tool = CalendarTool()
mcp_host.register_tool(calendar_tool)
transcript_tool = TranscriptTool()
mcp_host.register_tool(transcript_tool)
summarization_tool = SummarizationTool()
mcp_host.register_tool(summarization_tool)
jira_tool = JiraTool()
mcp_host.register_tool(jira_tool)
risk_tool = RiskTool()
mcp_host.register_tool(risk_tool)
# Register orchestrator agent wired to the same MCPHost
orchestrator = OrchestratorAgent(mcp_host=mcp_host)


class CalendarRequest(BaseModel):
    action: str
    start: Optional[Any] = None
    end: Optional[Any] = None
    calendar_id: Optional[str] = None
    event_data: Optional[dict] = None
    time_min: Optional[str] = None
    time_max: Optional[str] = None


class TranscriptRequest(BaseModel):
    transcripts: Optional[List[str]] = None
    chunk_size: Optional[int] = None
    # keep compatibility with orchestrator params
    data: Optional[Any] = None


@app.post("/mcp/calendar", dependencies=[Depends(verify_api_key)])
async def call_calendar(req: CalendarRequest):
    # create a short-lived session for this HTTP call
    session_id = mcp_host.create_session(agent_id="http-client")
    params = req.dict(exclude_none=True)
    result = await mcp_host.execute_tool(session_id, "calendar", params)
    mcp_host.end_session(session_id)
    return result


@app.post("/mcp/transcript", dependencies=[Depends(verify_api_key)])
async def call_transcript(req: TranscriptRequest):
    session_id = mcp_host.create_session(agent_id="http-client")
    params = req.dict(exclude_none=True)
    # allow `data` to alias `transcripts` for flexibility
    if "data" in params and "transcripts" not in params:
        params["transcripts"] = params.pop("data")
    result = await mcp_host.execute_tool(session_id, "transcript", params)
    mcp_host.end_session(session_id)
    return result


class OrchestrateRequest(BaseModel):
    message: str
    params: Optional[dict] = None


class SummarizeRequest(BaseModel):
    processed_transcripts: Optional[List[str]] = None
    mode: Optional[str] = None


class JiraRequest(BaseModel):
    action_items: Optional[List[Dict[str, Any]]] = None
    user: Optional[str] = None
    date: Optional[str] = None


class RiskRequest(BaseModel):
    meeting_id: Optional[str] = None
    summary: Optional[Dict[str, Any]] = None
    tasks: Optional[List[Dict[str, Any]]] = None
    progress: Optional[Dict[str, Any]] = None


@app.post("/mcp/orchestrate", dependencies=[Depends(verify_api_key)])
async def call_orchestrate(req: OrchestrateRequest):
    # delegate to the orchestrator agent which will create its own session and invoke tools
    result = await orchestrator.orchestrate(req.message, req.params or {})
    return result


@app.post("/mcp/summarize", dependencies=[Depends(verify_api_key)])
async def call_summarize(req: SummarizeRequest):
    session_id = mcp_host.create_session(agent_id="http-client")
    params = req.dict(exclude_none=True)
    # normalize parameter name to match tool expectations
    if "processed_transcripts" in params and "processed" not in params:
        params["processed"] = params.get("processed_transcripts")
    result = await mcp_host.execute_tool(session_id, "summarization", params)
    mcp_host.end_session(session_id)
    return result


@app.post("/mcp/jira", dependencies=[Depends(verify_api_key)])
async def call_jira(req: JiraRequest):
    session_id = mcp_host.create_session(agent_id="http-client")
    params = req.dict(exclude_none=True)
    # allow alternate key names
    if "items" in params and "action_items" not in params:
        params["action_items"] = params.pop("items")
    result = await mcp_host.execute_tool(session_id, "jira", params)
    mcp_host.end_session(session_id)
    return result


@app.post("/mcp/risk", dependencies=[Depends(verify_api_key)])
async def call_risk(req: RiskRequest):
    session_id = mcp_host.create_session(agent_id="http-client")
    params = req.dict(exclude_none=True)
    # allow flexibility in parameter names
    if "meeting_id" not in params and "meeting" in params:
        params["meeting_id"] = params.pop("meeting")
    result = await mcp_host.execute_tool(session_id, "risk", params)
    mcp_host.end_session(session_id)
    return result


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
