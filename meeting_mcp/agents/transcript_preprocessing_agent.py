"""Transcript preprocessing agent for meeting_mcp.

Provides simple cleaning/chunking for meeting transcripts. This agent
is synchronous and intended to be called from the `TranscriptTool` which
runs blocking work in a thread executor.
"""
from typing import List, Dict, Any
import logging

logger = logging.getLogger("meeting_mcp.agents.transcript_preprocessing_agent")


class TranscriptPreprocessingAgent:
    def __init__(self):
        self.agent_id = "transcript-preprocessor"
        self.name = "Transcript Preprocessing Agent"

    def process(self, transcripts: List[str], chunk_size: int = 1500) -> Dict[str, Any]:
        """Clean, normalize and chunk a list of transcript strings.

        `chunk_size` is the approximate number of words per chunk (default 1500).

        Returns a dict with `processed` key containing list of chunks.
        """
        import re
        import unicodedata

        contractions = {
            "can't": "cannot", "won't": "will not", "n't": " not", "'re": " are",
            "'s": " is", "'d": " would", "'ll": " will", "'t": " not",
            "'ve": " have", "'m": " am"
        }
        filler_words = [r'\bum\b', r'\buh\b', r'\byou know\b', r'\blike\b', r'\bokay\b', r'\bso\b', r'\bwell\b']
        speaker_tag_pattern = r'^\s*([A-Za-z]+ ?\d*):'
        timestamp_pattern = r'\[\d{1,2}:\d{2}(:\d{2})?\]'
        special_char_pattern = r'[^\w\s.,?!]'

        def expand_contractions(text: str) -> str:
            for k, v in contractions.items():
                text = re.sub(k, v, text)
            return text

        def clean_text(text: str) -> str:
            text = unicodedata.normalize('NFKC', text)
            text = text.lower()
            text = expand_contractions(text)
            text = re.sub(timestamp_pattern, '', text)
            text = re.sub(speaker_tag_pattern, '', text, flags=re.MULTILINE)
            for fw in filler_words:
                text = re.sub(fw, '', text)
            text = re.sub(special_char_pattern, '', text)
            text = re.sub(r'\s+', ' ', text)
            return text.strip()

        processed: List[str] = []
        total_words = 0
        for t in transcripts:
            t = (t or '').strip()
            if not t:
                continue
            t = clean_text(t)
            words = t.split()
            total_words += len(words)
            for i in range(0, len(words), chunk_size):
                chunk = ' '.join(words[i:i+chunk_size])
                if chunk:
                    processed.append(chunk)

        # Emit debug information at DEBUG level to help trace issues between backend/UI
        debug_info = {
            "input_transcripts": len(transcripts),
            "total_words": total_words,
            "chunk_size": chunk_size,
            "chunks_produced": len(processed),
            "sample_chunks": processed[:3]
        }
        logger.debug("TranscriptPreprocessing: %s", debug_info)

        return {"processed": processed, "debug": debug_info}


__all__ = ["TranscriptPreprocessingAgent"]
