import re
import json
import torch

def summarize_with_mistral(mistral_tokenizer, mistral_model, transcript, meeting_id):
    print("[Mistral] summarize_with_mistral called. Meeting ID:", meeting_id)
    # Accept either a string (single transcript) or a list (pre-chunked)
    if isinstance(transcript, list):
        transcript_chunks = [t for t in transcript if t and isinstance(t, str) and len(t.split()) >= 10]
        print(f"[Mistral] Received transcript as list. {len(transcript_chunks)} valid chunks.")
        if not transcript_chunks:
            print("[Mistral] No valid transcript chunks for summarization.")
            return {
                'meeting_id': meeting_id,
                'summary_text': "Transcript too short for summarization.",
                'action_items': []
            }
    else:
        if not transcript or not isinstance(transcript, str) or len(transcript.split()) < 10:
            print("[Mistral] Transcript too short for summarization.")
            return {
                'meeting_id': meeting_id,
                'summary_text': "Transcript too short for summarization.",
                'action_items': []
            }
        def chunk_text(text, max_words=1500):
            words = text.split()
            chunks = []
            for i in range(0, len(words), max_words):
                chunk = ' '.join(words[i:i+max_words])
                chunks.append(chunk)
            return chunks
        transcript_chunks = chunk_text(transcript, max_words=1500)
        print(f"[Mistral] Transcript split into {len(transcript_chunks)} chunk(s) (chunk size: 1500 words).")

    all_summaries = []
    all_action_items = []

    for idx, chunk in enumerate(transcript_chunks):
        print(f"[Mistral][Chunk {idx+1}] Processing chunk of length {len(chunk.split())} words.")
        mistral_prompt = (
            "You are an AI specialized in analyzing meeting transcripts.\n"
            "Your task is to produce:\n"
            "1. A clear and concise SUMMARY of the meeting as a numbered or bulleted list (do not use 'point 1', 'point 2', use real content).\n"
            "2. A list of ACTION ITEMS as an array of objects. Use issue_type: 'Story' for major feature creation and 'Task' or 'Bug' for technical sub-work. Each action item must include: summary, assignee, issue_type, and a logical due_date.\n"
            "3. A list of DECISIONS made during the meeting.\n"
            "4. A list of RISKS, blockers, or concerns raised.\n"
            "5. A list of FOLLOW-UP QUESTIONS that attendees should clarify.\n"
            "\n"
            "INSTRUCTIONS:\n"
            "- Read the provided meeting transcript thoroughly.\n"
            "- Do NOT invent information. Only extract what is explicitly or implicitly present.\n"
            "- If some sections have no information, return an empty list.\n"
            "- Keep summary short but complete (5–8 bullet points or numbers).\n"
            "- Use simple, business-friendly language.\n"
            "- DO NOT use placeholder text like 'point 1', 'point 2', '<summary bullet 1>', '<task>', etc.\n"
            "- DO NOT copy the example below. Fill with real meeting content.\n"
            "\n"
            "RETURN THE OUTPUT IN THIS EXACT JSON FORMAT (as a code block):\n"
            "```json\n"
            "{\n"
            "  \"summary\": [\"<summary bullet 1>\", \"<summary bullet 2>\"],\n"
            "  \"action_items\": [ {\"task\": \"<task>\", \"owner\": \"<owner>\", \"deadline\": \"<deadline>\"} ]\n"
            "}\n"
            "```\n"
            "\n"
            "TRANSCRIPT:\n"
            f"{chunk}\n"
        )
        # print(f"[Mistral][Chunk {idx+1}] Prompt sent to model (first 500 chars):\n", mistral_prompt[:500], "..." if len(mistral_prompt) > 500 else "")
        device = next(mistral_model.parameters()).device
        print(f"[Mistral][Chunk {idx+1}] Using device: {device}")
        encoded = mistral_tokenizer.encode_plus(
            mistral_prompt,
            truncation=True,
            max_length=4096,
            return_tensors="pt"
        )
        input_ids = encoded["input_ids"].to(device)
        attention_mask = encoded["attention_mask"].to(device)
        print(f"[Mistral][Chunk {idx+1}] Input IDs shape: {input_ids.shape}")
        summary_ids = mistral_model.generate(
            input_ids,
            attention_mask=attention_mask,
            max_new_tokens=512,
            do_sample=False,
            num_beams=4,
            early_stopping=True,
            pad_token_id=mistral_tokenizer.eos_token_id
        )
        mistral_output = mistral_tokenizer.decode(summary_ids[0], skip_special_tokens=True)
        print(f"[Mistral][Chunk {idx+1}] Model output (first 500 chars):\n{mistral_output[:500]}{'...' if len(mistral_output) > 500 else ''}")
        print(f"[Mistral][Chunk {idx+1}] Full Model output:\n{mistral_output}")
        def extract_last_json(text):
            # Find all top-level JSON objects and return the last one
            starts = []
            ends = []
            brace_count = 0
            start = None
            for i, c in enumerate(text):
                if c == '{':
                    if brace_count == 0:
                        start = i
                    brace_count += 1
                elif c == '}':
                    brace_count -= 1
                    if brace_count == 0 and start is not None:
                        starts.append(start)
                        ends.append(i+1)
                        start = None
            if starts and ends:
                # Return the last JSON block
                candidate = text[starts[-1]:ends[-1]]
                # Auto-fix: replace single quotes with double quotes, remove trailing commas
                import re
                fixed = candidate
                # Only replace single quotes if it looks like JSON (avoid breaking valid JSON)
                if fixed.count("'") > fixed.count('"'):
                    fixed = fixed.replace("'", '"')
                # Remove trailing commas before } or ]
                fixed = re.sub(r',([ \t\r\n]*[}\]])', r'\1', fixed)
                print(f"[Mistral][Chunk {idx+1}] Candidate JSON before parsing:\n{fixed}")
                return fixed
            return None

        json_str = extract_last_json(mistral_output)
        # Always initialize these to avoid UnboundLocalError
        summary_text = []
        action_items = []
        decisions = []
        risks = []
        follow_up_questions = []
        if json_str:
            print(f"[Mistral][Chunk {idx+1}] JSON block found in output.")
            try:
                parsed = json.loads(json_str)
                summary_text = parsed.get('summary', [])
                action_items = parsed.get('action_items', [])
                # New fields for decisions, risks, follow_up_questions
                decisions = parsed.get('decisions', [])
                risks = parsed.get('risks', [])
                follow_up_questions = parsed.get('follow_up_questions', [])
                print(f"[Mistral][Chunk {idx+1}] Parsed summary: {summary_text}")
                print(f"[Mistral][Chunk {idx+1}] Parsed action_items: {action_items}")
                print(f"[Mistral][Chunk {idx+1}] Parsed decisions: {decisions}")
                print(f"[Mistral][Chunk {idx+1}] Parsed risks: {risks}")
                print(f"[Mistral][Chunk {idx+1}] Parsed follow_up_questions: {follow_up_questions}")
            except Exception as e:
                print(f"[Mistral][Chunk {idx+1}] JSON parsing error: {e}")
        else:
            print(f"[Mistral][Chunk {idx+1}] No JSON block found in output.")
            summary_text = []
            action_items = []
        # Clean up and filter out empty/placeholder/point items
        def is_valid_summary_item(item):
            if not item or not isinstance(item, str):
                return False
            s = item.strip().lower()
            if s in ("point 1", "point 2", "point1", "point2", "", "-", "<summary bullet 1>", "<summary bullet 2>"):
                return False
            if s.startswith("point ") or s.startswith("<summary"):
                return False
            if '<' in s and '>' in s:
                return False
            return True
        def is_valid_action_item(item):
            if not item:
                return False
            if isinstance(item, dict):
                # Remove if any value is a placeholder like <task> or empty
                for v in item.values():
                    if isinstance(v, str) and (v.strip() == '' or v.strip().startswith('<')):
                        return False
                return any(v for v in item.values())
            if isinstance(item, str):
                s = item.strip()
                if s == '' or s.startswith('<'):
                    return False
                return True
            return False
        filtered_summaries = [s for s in (summary_text if isinstance(summary_text, list) else [summary_text]) if is_valid_summary_item(s)]
        filtered_action_items = [a for a in (action_items if isinstance(action_items, list) else [action_items]) if is_valid_action_item(a)]
        filtered_decisions = [d for d in (decisions if isinstance(decisions, list) else [decisions]) if is_valid_summary_item(d)]
        filtered_risks = [r for r in (risks if isinstance(r, list) else [risks]) if is_valid_summary_item(r)]
        filtered_follow_ups = [f for f in (follow_up_questions if isinstance(follow_up_questions, list) else [follow_up_questions]) if is_valid_summary_item(f)]
        print(f"[Mistral][Chunk {idx+1}] Filtered summary: {filtered_summaries}")
        print(f"[Mistral][Chunk {idx+1}] Filtered action_items: {filtered_action_items}")
        print(f"[Mistral][Chunk {idx+1}] Filtered decisions: {filtered_decisions}")
        print(f"[Mistral][Chunk {idx+1}] Filtered risks: {filtered_risks}")
        print(f"[Mistral][Chunk {idx+1}] Filtered follow_up_questions: {filtered_follow_ups}")
        all_summaries.extend(filtered_summaries)
        all_action_items.extend(filtered_action_items)
        if 'all_decisions' not in locals():
            all_decisions = []
        if 'all_risks' not in locals():
            all_risks = []
        if 'all_follow_ups' not in locals():
            all_follow_ups = []
        all_decisions.extend(filtered_decisions)
        all_risks.extend(filtered_risks)
        all_follow_ups.extend(filtered_follow_ups)
        print(f"[Mistral][Chunk {idx+1}] all_summaries so far: {all_summaries}")
        print(f"[Mistral][Chunk {idx+1}] all_action_items so far: {all_action_items}")
        print(f"[Mistral][Chunk {idx+1}] all_decisions so far: {all_decisions}")
        print(f"[Mistral][Chunk {idx+1}] all_risks so far: {all_risks}")
        print(f"[Mistral][Chunk {idx+1}] all_follow_ups so far: {all_follow_ups}")

    # print(f"[Mistral] FINAL all_summaries: {all_summaries}")
    # print(f"[Mistral] FINAL all_action_items: {all_action_items}")
    # Deduplicate summaries and action items
    def dedup_list(items):
        seen = set()
        deduped = []
        for item in items:
            key = json.dumps(item, sort_keys=True) if isinstance(item, dict) else str(item).strip().lower()
            if key not in seen:
                seen.add(key)
                deduped.append(item)
        return deduped
    print(f"[Mistral] Deduplicating final results...",all_summaries)
    deduped_summaries = dedup_list(all_summaries)
    print(f"[Mistral] Deduplicating final deduped_summaries ...",deduped_summaries)
    deduped_action_items = dedup_list(all_action_items)
    deduped_decisions = dedup_list(all_decisions) if 'all_decisions' in locals() else []
    deduped_risks = dedup_list(all_risks) if 'all_risks' in locals() else []
    deduped_follow_ups = dedup_list(all_follow_ups) if 'all_follow_ups' in locals() else []
    print(f"[Mistral] FINAL deduped_summaries: {deduped_summaries}")
    print(f"[Mistral] FINAL deduped_action_items: {deduped_action_items}")
    print(f"[Mistral] FINAL deduped_decisions: {deduped_decisions}")
    print(f"[Mistral] FINAL deduped_risks: {deduped_risks}")
    print(f"[Mistral] FINAL deduped_follow_ups: {deduped_follow_ups}")
    return {
        'meeting_id': meeting_id,
        'summary_text': deduped_summaries,
        'action_items': deduped_action_items,
        'decisions': deduped_decisions,
        'risks': deduped_risks,
        'follow_up_questions': deduped_follow_ups
    }
