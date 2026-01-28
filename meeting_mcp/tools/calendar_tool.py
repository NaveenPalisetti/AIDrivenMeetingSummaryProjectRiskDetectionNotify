import asyncio
from typing import Dict, Any

from meeting_mcp.core.mcp import MCPTool, MCPToolType
# Use the meeting-local Google Calendar adapter (avoids modifying `mcp` package)
from meeting_mcp.agents.google_calendar_adapter import MeetingMCPGoogleCalendar as MCPGoogleCalendar


class CalendarTool(MCPTool):
    def __init__(self):
        super().__init__(
            tool_id="calendar",
            tool_type=MCPToolType.CALENDAR,
            name="Calendar Tool",
            description="MCP Tool wrapper around Google Calendar client",
            api_endpoint="/mcp/calendar",
            auth_required=False,
            parameters={"action": "create|fetch|list|availability", "event_data": "dict", "start": "datetime|ISO", "end": "datetime|ISO"}
        )
        # Instantiate the blocking Google Calendar client; it expects credentials in project config.
        self._gcal = MCPGoogleCalendar()

    async def execute(self, params: Dict[str, Any] = None) -> Dict[str, Any]:
        params = params or {}
        action = params.get("action", "fetch")
        loop = asyncio.get_running_loop()

        try:
            # Allow overriding calendar per-call (useful when service-account vs user calendars differ)
            calendar_id = params.get("calendar_id")
            client = self._gcal
            if calendar_id:
                # Create a short-lived client tied to the requested calendar id
                client = MCPGoogleCalendar(calendar_id=calendar_id)

            if action == "create":
                event_data = params.get("event_data", {})
                event = await loop.run_in_executor(None, client.create_event, event_data)
                return {"status": "success", "event": event}

            if action == "availability":
                time_min = params.get("time_min")
                time_max = params.get("time_max")
                busy = await loop.run_in_executor(None, client.get_availability, time_min, time_max)
                return {"status": "success", "busy": busy}

            if action in ("fetch", "list"):
                start = params.get("start")
                end = params.get("end")
                events = await loop.run_in_executor(None, client.fetch_events, start, end)
                return {"status": "success", "events": events}

            return {"status": "error", "message": f"Unknown action: {action}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
