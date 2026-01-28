import sys
import pathlib
import json
import asyncio
import os
import streamlit as st
import logging
import re

# Enable debug logging to surface backend debug messages (e.g. preprocessor)
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("meeting_mcp.ui.streamlit")
# Also attach the project's rotating file logger so Streamlit logs go to Log/meeting_mcp.log
try:
    from Log.logger import setup_logging
    setup_logging()
except Exception as _e:
    # If file logging fails, continue with console logging only
    logger.debug("setup_logging() failed in streamlit UI: %s", _e)

# Ensure project root is importable when Streamlit runs the script.
# This is a small developer convenience (prefer running Streamlit from
# the project root or setting PYTHONPATH in production).
ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from meeting_mcp.system import create_system
from meeting_mcp.ui.renderers import (
    render_css,
    render_chat_messages,
    render_calendar_result,
    render_processed_chunks,
    render_summary_result,
    render_risk_result,
    render_notification_result,
)

# Page config
st.set_page_config(
    page_title="AI-Driven Meeting Summary & Project Risk Management",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)





@st.cache_resource
def create_runtime(mode: str = "hybrid"):
    # Returns: (mcp_host, inproc_host, tools, orchestrator)
    return create_system(mode=mode)


# No runtime selector in chat-only UX; use default wiring
mcp_host, inproc_host, tools, orchestrator = create_runtime()


# Initialize message history in session state
if "messages" not in st.session_state:
    st.session_state.messages = []


def add_message(role: str, content: str):
    st.session_state.messages.append({"role": role, "content": content})


def credentials_status() -> str:
    # Check env var or repo config path
    env_path = os.environ.get("MCP_SERVICE_ACCOUNT_FILE")
    if env_path and os.path.exists(env_path):
        return f"Using {env_path} (MCP_SERVICE_ACCOUNT_FILE)"
    fallback = os.path.join(os.path.dirname(__file__), "../config/credentials.json")
    fallback = os.path.abspath(fallback)
    if os.path.exists(fallback):
        return f"Using {fallback} (meeting_mcp/config/credentials.json)"
    return "No credentials found — set MCP_SERVICE_ACCOUNT_FILE or place credentials.json in meeting_mcp/config/"


render_css()

# Page heading similar to orchestrator_streamlit_client
st.title("🤖 AI-Driven Meeting Summary & Project Risk Management")
st.caption("A lightweight UI to run the orchestrator and inspect results.")


# Sidebar: summarizer/model selector (BART / Mistral)
with st.sidebar:
    st.header("🧠 Summarizer Model")
    if 'summarizer_model' not in st.session_state:
        st.session_state['summarizer_model'] = 'BART'
    model_choice = st.radio("Choose a summarizer:", ["BART", "Mistral"], key="summarizer_model")
    # (Risk detection is handled via chat commands and per-event buttons,
    # not via the sidebar. Use "detect risk" or the calendar event actions.)

col1 = st.container()

    # Chat-only message area using Streamlit's chat components
render_chat_messages(st.session_state.messages)

# Chat input: submit with Enter — runs the orchestrator by default
if prompt := st.chat_input("Describe your request (press Enter to send)"):
    add_message("user", prompt)
    with st.chat_message("user"):
        st.markdown(prompt)

    # Run orchestrator (chat-only UX; no params textarea)
    try:
        # Check for chat command that references last fetched events (e.g. "preprocess this <title>")
        handled = False
        # Ensure `result` is always defined to avoid NameError in downstream handling
        result = {"intent": "", "results": {}}
        lower = (prompt or "").lower()
        # Summarize command: if user asks to summarize a previously preprocessed meeting
        if "summarize" in lower and st.session_state.get("last_events"):
            import re

            title = None
            mq = re.search(r'["\u201c\u201d](?P<tq>[^"\u201c\u201d]+)["\u201c\u201d]', prompt)
            if mq:
                title = mq.group("tq").strip()
            else:
                m = re.search(r'summarize(?: this)?(?: meeting)?(?: for|:)?\s*(?P<tu>.+?)(?:$|\s{2,}|["\'])', prompt, flags=re.I)
                if m:
                    title = (m.group("tu") or "").strip()

            if title:
                title = re.split(r"\s{2,}|(?i:\sbut\s)|(?i:\sand\s)|[\"']", title)[0].strip()

            matched = None
            if not title:
                for ev in st.session_state.get("last_events", []):
                    summary = (ev.get("summary") or "")
                    if summary and summary.lower() in prompt.lower():
                        matched = ev
                        break
            if title and not matched:
                best_score = 0
                for ev in st.session_state.get("last_events", []):
                    summary = (ev.get("summary") or "")
                    if not summary:
                        continue
                    s_words = re.findall(r"\w+", summary.lower())
                    if not s_words:
                        continue
                    score = sum(1 for w in set(s_words) if w in title.lower())
                    if score > best_score:
                        best_score = score
                        matched = ev
            if not matched and title:
                for ev in st.session_state.get("last_events", []):
                    summary = (ev.get("summary") or "")
                    if title.lower() in summary.lower() or summary.lower() in title.lower():
                        matched = ev
                        break

            if matched:
                meeting_title = matched.get('summary')
                # Try to find cached processed chunks for this meeting
                cache = st.session_state.get('processed_cache', {})
                processed = cache.get(meeting_title)
                add_message("user", f"Summarize meeting: {meeting_title}")
                with st.chat_message("user"):
                    st.markdown(f"Summarize meeting: {meeting_title}")

                try:
                    logger.debug("Orchestrator preprocess call: meeting=%s", matched.get('summary'))
                    if not processed:
                        # If not preprocessed, trigger preprocess first
                        preprocess_text = matched.get("description") or matched.get("summary") or ""
                        params = {"transcripts": [preprocess_text], "chunk_size": 1500}
                        logger.debug("Preprocess params: %s", {k: (str(v)[:200] + '...' if isinstance(v, (str, list, dict)) and len(str(v))>200 else v) for k,v in params.items()})
                        proc_result = asyncio.run(orchestrator.orchestrate(f"preprocess transcripts for {meeting_title}", params))
                        logger.debug("Preprocess result (truncated): %s", str(proc_result)[:1000])
                        proc_summary = proc_result.get("results", {}).get("transcript") or proc_result.get("results")
                        if isinstance(proc_summary, dict) and proc_summary.get("status") == "success":
                            processed = proc_summary.get("processed")
                            # cache it for reuse
                            try:
                                if "processed_cache" not in st.session_state:
                                    st.session_state["processed_cache"] = {}
                                st.session_state["processed_cache"][meeting_title] = processed
                            except Exception:
                                pass

                    # Now call summarization tool via orchestrator
                    mode = st.session_state.get('summarizer_model', 'BART')
                    mode_param = 'bart' if mode.lower().startswith('b') else 'mistral'
                    logger.debug("Orchestrator summarize call: meeting=%s, mode=%s", meeting_title, mode_param)
                    params = {"processed_transcripts": processed or [], "mode": mode_param}
                    logger.debug("Summarize params: processed_count=%d", len(params.get("processed_transcripts", [])))
                    sum_result = asyncio.run(orchestrator.orchestrate(f"summarize meeting {meeting_title}", params))
                    logger.debug("Summarize result (truncated): %s", str(sum_result)[:2000])
                    sum_block = sum_result.get('results', {}).get('summarization') or sum_result.get('results')
                    if isinstance(sum_block, dict) and sum_block.get('status') == 'success':
                        summary_obj = sum_block.get('summary')
                    else:
                        # Tool-level fallback
                        summary_obj = sum_block

                    # Ensure `result` is defined for downstream handling
                    try:
                        result = {"intent": "summarize", "results": {"summarization": sum_block}}
                    except Exception:
                        result = {"intent": "summarize", "results": {"summarization": summary_obj}}

                    # Render summary and action items
                    add_message("assistant", f"Summary for {meeting_title} ready.")
                    with st.chat_message("assistant"):
                        render_summary_result(summary_obj, meeting_title, add_message)
                        try:
                            st.session_state['suppress_calendar_render'] = True
                        except Exception:
                            pass
                except Exception as e:
                    add_message("system", f"Error: {e}")
                    with st.chat_message("assistant"):
                        st.markdown(f"Error: {e}")

                handled = True
        # Detect risk command: mirror summarize flow but call orchestrator with risk intent
        if ("detect risk" in lower or "risk" in lower) and st.session_state.get("last_events"):

            title = None
            mq = re.search(r'["\u201c\u201d](?P<tq>[^"\u201c\u201d]+)["\u201c\u201d]', prompt)
            if mq:
                title = mq.group("tq").strip()
            else:
                m = re.search(r'detect\s*risks?(?: for|:)?\s*(?P<tu>.+?)(?:$|\s{2,}|["\'])', prompt, flags=re.I)
                if m:
                    title = (m.group("tu") or "").strip()

            if title:
                title = re.split(r"\s{2,}|(?i:\sbut\s)|(?i:\sand\s)|[\"']", title)[0].strip()

            matched = None
            if not title:
                for ev in st.session_state.get("last_events", []):
                    summary = (ev.get("summary") or "")
                    if summary and summary.lower() in prompt.lower():
                        matched = ev
                        break

            if title and not matched:
                best_score = 0
                for ev in st.session_state.get("last_events", []):
                    summary = (ev.get("summary") or "")
                    if not summary:
                        continue
                    s_words = re.findall(r"\w+", summary.lower())
                    if not s_words:
                        continue
                    score = sum(1 for w in set(s_words) if w in title.lower())
                    if score > best_score:
                        best_score = score
                        matched = ev

            if not matched and title:
                for ev in st.session_state.get("last_events", []):
                    summary = (ev.get("summary") or "")
                    if title.lower() in summary.lower() or summary.lower() in title.lower():
                        matched = ev
                        break

            if matched:
                meeting_title = matched.get('summary') or matched.get('id')
                # Build params similar to event-based detect
                params = {"meeting_id": meeting_title, "summary": {"summary_text": matched.get('description') or matched.get('summary')}}
                if st.session_state.get('last_action_items'):
                    params['tasks'] = st.session_state.get('last_action_items')
                add_message("user", f"Detect risks for: {meeting_title}")
                with st.chat_message("user"):
                    st.markdown(f"Detect risks for: {meeting_title}")
                try:
                    logger.debug("Orchestrator risk call (chat): %s", meeting_title)
                    risk_result = asyncio.run(orchestrator.orchestrate(f"detect risk for {meeting_title}", params))
                    logger.debug("Risk result (chat): %s", str(risk_result)[:1000])
                    add_message("assistant", f"Risk detection for {meeting_title} completed.")
                    with st.chat_message("assistant"):
                                render_risk_result(risk_result, meeting_title if 'meeting_title' in locals() else None, add_message)
                except Exception as e:
                    add_message("system", f"Error running risk detection: {e}")
                    with st.chat_message("assistant"):
                        st.markdown(f"Error running risk detection: {e}")

                handled = True
        # Create Jira command: allow user to type "create jira: <task>" or "create jira for <task>"
        if ("create jira" in lower or "createissue" in lower) and st.session_state.get('last_action_items'):
            try:
                import re
                # Extract quoted title first
                title = None
                mq = re.search(r'["\u201c\u201d](?P<tq>[^"\u201c\u201d]+)["\u201c\u201d]', prompt)
                if mq:
                    title = mq.group('tq').strip()
                else:
                    m = re.search(r'create\s*jira(?:\s*for|:)?\s*(?P<tu>.+)$', prompt, flags=re.I)
                    if m:
                        title = (m.group('tu') or '').strip()

                matched = None
                items = st.session_state.get('last_action_items', [])
                if title:
                    # try numeric index
                    if title.isdigit():
                        idx = int(title) - 1
                        if 0 <= idx < len(items):
                            matched = items[idx]
                    if not matched:
                        best = None
                        best_score = 0
                        for it in items:
                            text = (it.get('summary') or it.get('task') or it.get('title') or '')
                            if not text:
                                continue
                            score = sum(1 for w in set(re.findall(r"\w+", text.lower())) if w in title.lower())
                            if score > best_score:
                                best_score = score
                                best = it
                        if best_score > 0:
                            matched = best

                # If matched, call orchestrator's jira tool
                if matched:
                    task = matched.get('summary') or matched.get('task') or matched.get('title') or ''
                    owner = matched.get('assignee') or matched.get('owner') or matched.get('assigned_to') or None
                    due = matched.get('due') or matched.get('deadline') or matched.get('due_date') or None
                    add_message('user', f"Create Jira: {task}")
                    with st.chat_message('user'):
                        st.markdown(f"Create Jira: {task}")
                    params = {"task": task, "owner": owner, "deadline": due}
                    logger.debug("Orchestrator jira call: task=%s", (task or '')[:200])
                    try:
                        jira_result = asyncio.run(orchestrator.orchestrate(f"create jira for {task}", params))
                        logger.debug("Jira result: %s", str(jira_result)[:1000])
                        add_message('assistant', f"Jira creation result: {jira_result.get('results', {})}")
                        with st.chat_message('assistant'):
                            st.markdown(f"Jira creation result:\n\n```json\n{json.dumps(jira_result, indent=2)}\n```")
                    except Exception as e:
                        add_message('system', f"Error creating Jira: {e}")
                        with st.chat_message('assistant'):
                            st.markdown(f"Error creating Jira: {e}")
                    handled = True
            except Exception as e:
                logger.exception("Failed to handle create jira command: %s", e)
        # Notify command: allow user to type "notify <meeting>" or "send notification for <meeting>"
        if ("notify" in lower or "send notification" in lower or "notify team" in lower) and st.session_state.get('last_events'):
            try:
                import re
                title = None
                mq = re.search(r'["\u201c\u201d](?P<tq>[^"\u201c\u201d]+)["\u201c\u201d]', prompt)
                if mq:
                    title = mq.group('tq').strip()
                else:
                    m = re.search(r'notify(?:\s+team)?(?:\s+for|:)?\s*(?P<tu>.+)$', prompt, flags=re.I)
                    if m:
                        title = (m.group('tu') or '').strip()

                matched = None
                items = st.session_state.get('last_events', [])
                if not title:
                    for ev in items:
                        summary = (ev.get('summary') or '')
                        if summary and summary.lower() in prompt.lower():
                            matched = ev
                            break

                if title and not matched:
                    best = None
                    best_score = 0
                    for ev in items:
                        text = (ev.get('summary') or ev.get('description') or '')
                        if not text:
                            continue
                        score = sum(1 for w in set(re.findall(r"\w+", text.lower())) if w in title.lower())
                        if score > best_score:
                            best_score = score
                            best = ev
                    if best_score > 0:
                        matched = best

                if matched:
                    meeting_title = matched.get('summary') or matched.get('id')
                    params = {"meeting_id": meeting_title, "summary": {"summary_text": matched.get('description') or matched.get('summary')}}
                    if st.session_state.get('last_action_items'):
                        params['tasks'] = st.session_state.get('last_action_items')
                    if st.session_state.get('last_risks'):
                        params['risks'] = st.session_state.get('last_risks')

                    add_message('user', f"Notify team for: {meeting_title}")
                    with st.chat_message('user'):
                        st.markdown(f"Notify team for: {meeting_title}")

                    try:
                        logger.debug("Orchestrator notify call: %s", meeting_title)
                        notify_result = asyncio.run(orchestrator.orchestrate(f"notify for {meeting_title}", params))
                        logger.debug("Notify result: %s", str(notify_result)[:1000])
                        add_message('assistant', f"Notification result for {meeting_title}: {notify_result.get('results', {})}")
                        with st.chat_message('assistant'):
                            try:
                                render_notification_result(notify_result, meeting_title, add_message)
                            except Exception:
                                st.markdown(f"Notification result:\n\n```json\n{json.dumps(notify_result, indent=2)}\n```")
                    except Exception as e:
                        add_message('system', f"Error sending notification: {e}")
                        with st.chat_message('assistant'):
                            st.markdown(f"Error sending notification: {e}")

                    handled = True
            except Exception as e:
                logger.exception("Failed to handle notify command: %s", e)
        if "preprocess" in lower and st.session_state.get("last_events"):
            import re

            # Robust title extraction:
            # 1. Prefer the first quoted string if present
            # 2. Else try to capture text immediately following the preprocess phrase
            # 3. Fallback to fuzzy/overlap matching against cached `last_events`
            title = None
            mq = re.search(r'["\u201c\u201d](?P<tq>[^"\u201c\u201d]+)["\u201c\u201d]', prompt)
            if mq:
                title = mq.group("tq").strip()
            else:
                m = re.search(r'preprocess(?: this)?(?: meeting)?(?: for|:)?\s*(?P<tu>.+?)(?:$|\s{2,}|["\'])', prompt, flags=re.I)
                if m:
                    title = (m.group("tu") or "").strip()

            if title:
                # Heuristic clean: stop at obvious separators or trailing commentary
                title = re.split(r"\s{2,}|(?i:\sbut\s)|(?i:\sand\s)|[\"']", title)[0].strip()

            matched = None
            # If we didn't get a clean title, try substring match first
            if not title:
                for ev in st.session_state.get("last_events", []):
                    summary = (ev.get("summary") or "")
                    if summary and summary.lower() in prompt.lower():
                        matched = ev
                        break

            # If we got a title, pick the best event by word-overlap score
            if title and not matched:
                best_score = 0
                for ev in st.session_state.get("last_events", []):
                    summary = (ev.get("summary") or "")
                    if not summary:
                        continue
                    s_words = re.findall(r"\w+", summary.lower())
                    if not s_words:
                        continue
                    score = sum(1 for w in set(s_words) if w in title.lower())
                    if score > best_score:
                        best_score = score
                        matched = ev

            # final fallback: simple contains checks
            if not matched and title:
                for ev in st.session_state.get("last_events", []):
                    summary = (ev.get("summary") or "")
                    if title.lower() in summary.lower() or summary.lower() in title.lower():
                        matched = ev
                        break

            if matched:
                preprocess_text = matched.get("description") or matched.get("summary") or ""
                add_message("user", f"Preprocess meeting: {matched.get('summary')}")
                with st.chat_message("user"):
                    st.markdown(f"Preprocess meeting: {matched.get('summary')}")

                try:
                    params = {"transcripts": [preprocess_text], "chunk_size": 1500}
                    logger.debug("Orchestrator preprocess call (explicit): meeting=%s", matched.get('summary'))
                    logger.debug("Preprocess params: %s", {k: (str(v)[:200] + '...' if isinstance(v, (str, list, dict)) and len(str(v))>200 else v) for k,v in params.items()})
                    proc_result = asyncio.run(orchestrator.orchestrate(f"preprocess transcripts for {matched.get('summary')}", params))
                    logger.debug("Preprocess result (truncated): %s", str(proc_result)[:1000])
                    # ensure downstream code that expects `result` has a value
                    result = proc_result
                    proc_summary = proc_result.get("results", {}).get("transcript") or proc_result.get("results")
                    if isinstance(proc_summary, dict) and proc_summary.get("status") == "success":
                        processed = proc_summary.get("processed", []) if isinstance(proc_summary, dict) else None
                        if isinstance(processed, list):
                            assistant_md = f"Preprocessed {len(processed)} chunk(s) for {matched.get('summary')}."
                        else:
                            assistant_md = "Preprocessing completed."
                    else:
                        assistant_md = f"Preprocessing result: {proc_result}"

                    add_message("assistant", assistant_md)
                    with st.chat_message("assistant"):
                        st.markdown(assistant_md)
                        if isinstance(proc_summary, dict) and proc_summary.get("status") == "success":
                            processed = proc_summary.get("processed")
                            debug = proc_summary.get("debug") if isinstance(proc_summary, dict) else None
                            if processed:
                                render_processed_chunks(processed, matched.get('summary'), add_message, debug)
                                try:
                                    st.session_state['suppress_calendar_render'] = True
                                except Exception:
                                    pass
                except Exception as e:
                    add_message("system", f"Error: {e}")
                    with st.chat_message("assistant"):
                        st.markdown(f"Error: {e}")

                handled = True

        if not handled:
            logger.debug("Orchestrator free-form call: prompt=%s", (prompt or '')[:500])
            result = asyncio.run(orchestrator.orchestrate(prompt, {}))
            logger.debug("Orchestrator free-form result (truncated): %s", str(result)[:2000])

        # Add a compact system entry for history (keeps messages small)
        short_summary = result.get("intent", "")
        add_message("system", f"intent: {short_summary}")
        # If a preprocess action just ran and requested suppression, avoid re-rendering calendar/JSON
        suppress = st.session_state.pop('suppress_calendar_render', False)

        # Prepare assistant content to persist in session history
        calendar_block = None if suppress else (result.get("results", {}).get("calendar") if isinstance(result, dict) else None)
        if calendar_block and calendar_block.get("status") == "success":
            events = calendar_block.get("events", [])
            # persist most recent fetched events so chat commands can reference them
            st.session_state['last_events'] = events
            # Build a concise markdown summary for session history
            if not events:
                assistant_md = "No calendar events found for the requested range."
            else:
                lines = [f"**Calendar:** {len(events)} event(s) returned"]
                for ev in events[:10]:
                    when = ev.get('start', {}).get('dateTime') or ev.get('start', {}).get('date')
                    lines.append(f"- {when} — {ev.get('summary')}")
                if len(events) > 10:
                    lines.append(f"...and {len(events)-10} more events")
                assistant_md = "\n".join(lines)
        else:
            # Fallback: short textual summary
            assistant_md = f"Result: intent={result.get('intent')}"

        # Persist assistant summary to session history so previous responses remain
        add_message("assistant", assistant_md)

        # Render assistant response using centralized renderers
        with st.chat_message("assistant"):
            if calendar_block:
                render_calendar_result(calendar_block, orchestrator, add_message)
            else:
                # If we suppressed rendering (e.g. after a preprocess action), don't show raw JSON fallback
                if not suppress:
                    st.markdown("Result:\n\n" + "```json\n" + json.dumps(result, indent=2) + "\n```")
    except Exception as e:
        add_message("system", f"Error: {e}")
        with st.chat_message("assistant"):
            st.markdown(f"Error: {e}")

# Status & Tools hidden in chat-only mode per user request
