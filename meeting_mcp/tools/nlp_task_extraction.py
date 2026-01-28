"""Simple, dependency-free NLP helpers to extract structured tasks from text.

This is intentionally lightweight and heuristic-driven so it can run in
development environments without heavy ML dependencies. It returns a list
of dicts with keys: `title`, `owner`, `due`, and `raw`.
"""
import re
from typing import List, Dict
import logging
import sys

logger = logging.getLogger("meeting_mcp.nlp_task_extraction")


def _split_sentences(text: str) -> List[str]:
    # Basic sentence splitter using punctuation
    if not text:
        return []
    # Normalize whitespace
    txt = re.sub(r"\s+", " ", text.strip())
    # Split on sentence enders (., ?, !) followed by space and capital letter
    parts = re.split(r'(?<=[\.\?!])\s+', txt)
    return [p.strip() for p in parts if p.strip()]


def _find_owner(sentence: str):
    # Look for patterns like 'Alice (PO)', 'assign to Alice', 'Alice will', 'owner: Alice'
    m = re.search(r"owner:\s*([A-Z][a-zA-Z\-]+)", sentence, flags=re.I)
    if m:
        return m.group(1)
    m = re.search(r"assign(?:ed)?(?: to)?\s+([A-Z][a-zA-Z\-]+)", sentence, flags=re.I)
    if m:
        return m.group(1)
    m = re.search(r"([A-Z][a-zA-Z\-]+)\s*\(", sentence)
    if m:
        return m.group(1)
    m = re.search(r"([A-Z][a-zA-Z\-]+)\s+(will|shall|should|can|must)\b", sentence)
    if m:
        return m.group(1)
    # Match patterns like 'sarah to review' or 'David, to review' (common shorthand)
    m = re.search(r"([A-Za-z][a-zA-Z\-]+)\s*(?:,)?\s+to\s+\w+", sentence, flags=re.I)
    if m:
        return m.group(1)
    return None


def _find_due(sentence: str):
    # Very small set of due-date patterns: 'by <date>', 'by Friday', 'due <date>'
    m = re.search(r"by\s+([A-Z][a-z]+\b|\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})", sentence, flags=re.I)
    if m:
        return m.group(1)
    m = re.search(r"due\s+(on\s+)?([A-Z][a-z]+\b|\d{1,2}/\d{1,2}/\d{2,4})", sentence, flags=re.I)
    if m:
        return m.group(2)
    return None


def _is_action_sentence(sentence: str) -> bool:
    # Deprecated: replaced by scoring-based check in extract_tasks_structured
    s = sentence.lower()
    return False


def _score_action_sentence(sentence: str) -> float:
    """Return a confidence score [0..1] that the sentence represents an actionable task.

    Heuristics used (simple, no external deps):
    - +0.4 if an explicit owner pattern exists (owner/email/name)
    - +0.3 if a strong action verb is present (assign/create/implement/prepare/fix/verify/test/review)
    - +0.2 if a due-date pattern is present (by Friday / due ...)
    - -0.5 if the sentence is conditional/hypothetical (starts with 'if', contains 'might', 'could', 'when' with conditional sense)
    - small bonus for imperative-like phrasing (starts with a verb)
    """
    if not sentence:
        return 0.0
    s = sentence.strip()
    low = s.lower()

    # Immediately filter obvious non-actions: conditionals and hypotheticals
    conditional_markers = [" if ", "^if ", " might ", " could ", " maybe ", " may ", " if we ", "when we ", "when the "]
    for cm in conditional_markers:
        if cm.strip().startswith("^"):
            # regex anchor check
            import re
            if re.match(cm[1:], low):
                return 0.0
        else:
            if cm in low:
                return 0.0

    score = 0.0

    # Owner presence
    if _find_owner(s):
        score += 0.4

    # Due date presence
    if _find_due(s):
        score += 0.2

    # Strong action verbs
    strong_verbs = ["assign", "implement", "create", "prepare", "fix", "verify", "test", "review", "document", "schedule", "deliver", "investigate", "follow up", "follow-up", "follow-up:"]
    if any(v in low for v in strong_verbs):
        score += 0.3

    # Imperative start (e.g., 'Prepare the report', 'Create a ticket')
    import re
    if re.match(r"^[A-Za-z]+\s", s):
        first = re.match(r"^([A-Za-z]+)", s).group(1)
        # common verbs list (small) — if first word is a verb, give small boost
        verbs_boost = {"prepare", "create", "assign", "investigate", "implement", "fix", "verify", "test", "review", "document", "schedule"}
        if first.lower() in verbs_boost:
            score += 0.1

    # Length heuristic: extremely long sentences are less likely single actionable items
    if len(s) > 400:
        score = max(0.0, score - 0.2)

    # Cap score
    if score > 1.0:
        score = 1.0
    return score


def extract_tasks_structured(text: str, max_tasks: int = 10, min_confidence: float = 0.4) -> List[Dict]:
    """Extract up to `max_tasks` structured tasks from `text`.

    Returns list of dicts: {"title": str, "owner": Optional[str], "due": Optional[str], "raw": str}
    """
    if not text or not isinstance(text, str):
        return []
    sentences = _split_sentences(text)
    tasks = []
    for sent in sentences:
        score = _score_action_sentence(sent)
        logger.debug("Sentence: %s | score=%.2f", sent, score)
        if score >= min_confidence:
            owner = _find_owner(sent)
            due = _find_due(sent)
            # Create a concise title: strip speaker prefixes like 'Vikram (Senior Dev):'
            title = re.sub(r"^[A-Za-z]+\s*\([^\)]*\):?\s*", "", sent).strip()
            # Limit title length
            if len(title) > 200:
                title = title[:197].rstrip() + "..."
            task = {
                "title": title,
                "owner": owner,
                "due": due,
                "raw": sent,
                "confidence": round(score, 2)
            }
            tasks.append(task)
            logger.debug("Added task: %s", task)
        if len(tasks) >= max_tasks:
            break
    return tasks


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    if len(sys.argv) > 1:
        text = " ".join(sys.argv[1:])
    else:
        text = "Assign to Alice: implement the new index by Friday. Bob (QA): verify the audit logs."
    logger.info("Running extractor on input (len=%d)", len(text))
    tasks = extract_tasks_structured(text, max_tasks=20, min_confidence=0.4)
    import json
    print(json.dumps(tasks, indent=2))
