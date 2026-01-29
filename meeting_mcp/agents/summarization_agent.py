import os
import asyncio
import json
import hashlib
import logging
import traceback
from typing import List, Dict, Any

# Local summarizers (meeting-scoped). These mirror the behaviour in the
# project's `mcp/agents` but live inside `meeting_mcp` to avoid importing
# implementation from the global `mcp` package.
from meeting_mcp.agents.bart_summarizer import summarize_with_bart
from meeting_mcp.agents.mistral_summarizer import summarize_with_mistral
from meeting_mcp import config as mm_config

logger = logging.getLogger("meeting_mcp.summarization")


def get_bart_model():
    if not hasattr(get_bart_model, "tokenizer") or not hasattr(get_bart_model, "model"):
        # Resolve BART model path via centralized helper in meeting_mcp.config
        bart_drive_path = mm_config.get_bart_model_path()
        if bart_drive_path:
            model_path = bart_drive_path
        else:
            # Default local model folder inside the meeting_mcp package
            model_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "models", "bart_finetuned_meeting_summary"))

        logger.info("Loading BART model from: %s", model_path)
        # Only raise if we're using the default local model and it's missing
        if (not bart_drive_path) and (not os.path.exists(model_path)):
            raise FileNotFoundError(f"BART model path not found: {model_path}")

        from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
        logger.info("Loading BART model from: %s", model_path)
        get_bart_model.tokenizer = AutoTokenizer.from_pretrained(model_path)
        logger.info("Loading BART get_bart_model.tokenizer  %s", get_bart_model.tokenizer)
        get_bart_model.model = AutoModelForSeq2SeqLM.from_pretrained(model_path)
        logger.info("Loading BART get_bart_model.get_bart_model.model  %s", get_bart_model.model)
    return get_bart_model.tokenizer, get_bart_model.model


def get_mistral_model():
    # Attempt to load a local Mistral model when requested by mode.
    # Do not require an environment flag — selection of mode ('mistral') drives loading.
    if not hasattr(get_mistral_model, "tokenizer") or not hasattr(get_mistral_model, "model"):
        model_path = mm_config.get_mistral_model_path() or os.environ.get("MISTRAL_MODEL_PATH") or "/content/mistral-7B-Instruct-v0.2"
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Mistral model path not found: {model_path}. Set a valid path via meeting_mcp.config or the MISTRAL_MODEL_PATH env var.")
        logger.info("Loading Mistral model from: %s", model_path)
        from transformers import AutoTokenizer, AutoModelForCausalLM
        from transformers import BitsAndBytesConfig
        import torch
        if not torch.cuda.is_available():
            raise RuntimeError("No CUDA GPU detected. Mistral requires a GPU. Set MISTRAL_ENABLED=0 to disable.")
        get_mistral_model.tokenizer = AutoTokenizer.from_pretrained(model_path)
        try:
            get_mistral_model.model = AutoModelForCausalLM.from_pretrained(
                model_path,
                device_map="cuda",
                quantization_config=BitsAndBytesConfig(load_in_4bit=True)
            )
        except Exception:
            get_mistral_model.model = AutoModelForCausalLM.from_pretrained(model_path, device_map="cuda")
    return get_mistral_model.tokenizer, get_mistral_model.model


class SummarizationAgent:
    def __init__(self, mode: str = "auto"):
        self.mode = mode

    def summarize_protocol(self, processed_transcripts: List[str] = None, mode: str = None, **kwargs) -> Dict[str, Any]:
        processed_transcripts = processed_transcripts or []
        mode = (mode or self.mode) or "auto"
        if isinstance(mode, str):
            mode = mode.lower()

        # Debug: record input characteristics
        full_transcript = "\n".join(processed_transcripts)
        # Log incoming kwargs for traceability (exclude large payloads)
        if kwargs:
            try:
                logger.debug("summarize_protocol called with kwargs: %s", {k: (str(v)[:200] + '...' if isinstance(v, (str, list, dict)) and len(str(v))>200 else v) for k,v in kwargs.items()})
            except Exception:
                logger.debug("summarize_protocol called with kwargs (unrepresentable)")
        # Preview transcript safely (avoid logging full sensitive text)
        try:
            preview = full_transcript[:1000]
            logger.debug("Transcript preview (first 1000 chars): %s", preview)
        except Exception:
            logger.debug("Transcript preview unavailable")
        try:
            digest = hashlib.sha256(full_transcript.encode("utf-8")).hexdigest() if full_transcript else ""
        except Exception:
            digest = "<sha-error>"
        # Debug: token count and sample tokens (cheap, whitespace-based)
        try:
            tokens = full_transcript.split()
            logger.debug("full_transcript token_count=%d, first_tokens=%s", len(tokens), tokens[:50])
            # If a HuggingFace tokenizer is already loaded, show its token count too (no model load)
            if hasattr(get_bart_model, "tokenizer"):
                try:
                    hf_tok = get_bart_model.tokenizer(full_transcript)
                    hf_count = len(hf_tok.get("input_ids", []))
                    logger.debug("hf_token_count=%d", hf_count)
                except Exception:
                    logger.debug("HF tokenizer present but tokenization failed")
        except Exception:
            logger.debug("Failed to compute tokens for transcript")
        logger.debug("Summarize called: mode=%s, chunks=%d, transcript_sha256=%s", mode, len(processed_transcripts), digest)
        if processed_transcripts:
            sample = processed_transcripts[0][:300]
            logger.debug("Sample first chunk: %s", sample)
        summary = None
        action_items = []
        download_link = None
        
        if mode == "bart":
            try:
                logger.debug("Attempting BART summarization (digest=%s)", digest)
                tokenizer, model = get_bart_model()
                summary_obj = summarize_with_bart(tokenizer, model, full_transcript, "meeting")
                summary = summary_obj.get('summary_text', '')
                action_items = summary_obj.get('action_items', [])
                download_link = summary_obj.get('download_link', None)
                logger.info("BART summary generated: summary_len=%d, action_items=%d", len(summary or ""), len(action_items))
            except Exception as e:
                logger.exception("BART summarization failed: %s", e)
                summary = full_transcript[:300] + ("..." if len(full_transcript) > 300 else f" [BART error: {e}]")
        elif mode == "mistral":
            try:
                logger.debug("Attempting Mistral summarization (digest=%s)", digest)
                mistral_tokenizer, mistral_model = get_mistral_model()
                summary_obj = summarize_with_mistral(mistral_tokenizer, mistral_model, full_transcript, "meeting")
                summary = summary_obj.get('summary_text', '')
                action_items = summary_obj.get('action_items', [])
                download_link = summary_obj.get('download_link', None)
                logger.info("Mistral summary generated: summary_len=%d, action_items=%d", len(summary or ""), len(action_items))
            except Exception as e:
                # fallback to bart if mistral fails
                logger.exception("Mistral summarization failed, falling back to BART: %s", e)
                try:
                    tokenizer, model = get_bart_model()
                    summary_obj = summarize_with_bart(tokenizer, model, full_transcript, "meeting")
                    summary = summary_obj.get('summary_text', '')
                    action_items = summary_obj.get('action_items', [])
                    download_link = summary_obj.get('download_link', None)
                except Exception as e2:
                    logger.exception("Fallback BART also failed: %s", e2)
                    summary = full_transcript[:300] + ("..." if len(full_transcript) > 300 else f" [Mistral/BART error: {e}; {e2}]")
        else:
            # auto / fallback: try bart, then mistral
            try:
                logger.debug("Auto mode: trying BART (digest=%s)", digest)
                tokenizer, model = get_bart_model()
                summary_obj = summarize_with_bart(tokenizer, model, full_transcript, "meeting")
                summary = summary_obj.get('summary_text', '')
                action_items = summary_obj.get('action_items', [])
                download_link = summary_obj.get('download_link', None)
                logger.info("Auto-BART summary generated: summary_len=%d, action_items=%d", len(summary or ""), len(action_items))
            except Exception:
                try:
                    logger.debug("Auto mode: BART failed, trying Mistral (digest=%s)", digest)
                    mistral_tokenizer, mistral_model = get_mistral_model()
                    summary_obj = summarize_with_mistral(mistral_tokenizer, mistral_model, full_transcript, "meeting")
                    summary = summary_obj.get('summary_text', '')
                    action_items = summary_obj.get('action_items', [])
                    download_link = summary_obj.get('download_link', None)
                    logger.info("Auto-Mistral summary generated: summary_len=%d, action_items=%d", len(summary or ""), len(action_items))
                except Exception:
                    summary = full_transcript[:300]

        result = {
            "summary": summary or "No summary generated.",
            "action_items": action_items,
            "download_link": download_link,
            "mode": mode,
            "transcript_length": len(full_transcript)
        }
        logger.debug("Summarization result: mode=%s, transcript_len=%d, summary_len=%d", mode, len(full_transcript), len(result.get("summary", "")))
        # Log result summary and action item count (truncate summary to avoid huge logs)
        try:
            result_log = {
                "mode": mode,
                "transcript_len": len(full_transcript),
                "summary_preview": (result.get("summary") or "")[:1000],
                "action_item_count": len(result.get("action_items", []))
            }
            logger.debug("Summarization output: %s", result_log)
        except Exception:
            logger.debug("Failed to log summarization output")
        return result

    async def summarize(self, meeting_id: str, transcript: str) -> Dict[str, Any]:
        loop = asyncio.get_running_loop()
        logger.debug("summarize called: meeting_id=%s, transcript_len=%d, mode=%s", meeting_id, len(transcript or ""), self.mode)
        result = await loop.run_in_executor(None, self.summarize_protocol, [transcript], self.mode)
        logger.debug("summarize completed: meeting_id=%s, result_summary_len=%d", meeting_id, len(result.get("summary", "")))
        return result


__all__ = ["SummarizationAgent"]
