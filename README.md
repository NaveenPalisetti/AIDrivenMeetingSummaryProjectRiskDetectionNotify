# AIDrivenMeetingSummaryProjectRiskDetection_1

This folder is a focused scaffold for the canonical MCP/A2A work in this workspace (renamed from `wMCP_1`).

Purpose:
- Provide a minimal, self-contained example of one agent (CalendarAgent) following the ITIncidentResponse approach.
- Keep protocol types local to the scaffold to avoid dependency coupling while you iterate.

Contents:
- `meeting_mcp/protocols/a2a.py` — minimal A2A datatypes (`AgentCard`, `AgentCapability`, `A2AMessage`, `PartType`, `A2ATask`).
- `meeting_mcp/agents/calendar_agent.py` — Calendar agent that exposes `create_event` and `list_events` methods and A2A-friendly wrappers.

Notes:
- This is a scaffold only; integrations (Google Calendar API, persistent stores, etc.) are represented as placeholders for you to fill.
- No production credentials or external calls are included.

When ready, I can extend this scaffold to add an MCP tool wrapper, FastAPI endpoints, and tests.
