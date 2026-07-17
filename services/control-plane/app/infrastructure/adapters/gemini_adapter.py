from __future__ import annotations

import json
import logging
import requests
import time
from typing import Tuple, List, Dict
from collections import defaultdict
from datetime import datetime, timedelta

from app.application.ports.creative_planning_provider import CreativePlanningProvider

logger = logging.getLogger(__name__)


class ModelQuotaTracker:
    """Track which models are exhausted and when to retry them"""
    
    def __init__(self):
        self._exhausted_until = {}  # model -> timestamp when quota resets
        self._last_successful_model = None
        self._usage_counter = defaultdict(int)  # track usage per model
        
    def mark_quota_exhausted(self, model: str, retry_after_seconds: int = 60):
        """Mark a model as quota exhausted for X seconds"""
        reset_time = datetime.now() + timedelta(seconds=retry_after_seconds)
        self._exhausted_until[model] = reset_time
        logger.info(f"Model {model} marked exhausted until {reset_time}")
        
    def mark_restricted(self, model: str):
        """Mark a model as permanently restricted (24 hours)"""
        self.mark_quota_exhausted(model, retry_after_seconds=86400)  # 24 hours
        
    def mark_success(self, model: str):
        """Mark a model as successfully used"""
        self._last_successful_model = model
        self._usage_counter[model] += 1
        # Clear exhausted flag if it was set
        self._exhausted_until.pop(model, None)
        
    def is_available(self, model: str) -> bool:
        """Check if a model is available (not exhausted)"""
        if model not in self._exhausted_until:
            return True
        return datetime.now() >= self._exhausted_until[model]
    
    def get_sorted_models(self, models: List[str]) -> List[str]:
        """Sort models by: last successful > least used > available > original order"""
        available = [m for m in models if self.is_available(m)]
        exhausted = [m for m in models if not self.is_available(m)]
        
        # Prioritize last successful model
        if self._last_successful_model and self._last_successful_model in available:
            available.remove(self._last_successful_model)
            available.insert(0, self._last_successful_model)
        
        # Sort remaining by usage (least used first) for load balancing
        remaining = sorted(
            [m for m in available if m != self._last_successful_model],
            key=lambda m: self._usage_counter[m]
        )
        
        return [self._last_successful_model] + remaining if self._last_successful_model in available else remaining + exhausted


# Global singleton tracker (persists across requests in same process)
_quota_tracker = ModelQuotaTracker()


class GeminiCreativePlanningAdapter(CreativePlanningProvider):
    def __init__(self, request_timeout_seconds: int = 30) -> None:
        self._timeout = request_timeout_seconds

    def generate_proposal(
        self,
        *,
        prompt: str,
        history: list[dict[str, str]],
        creation_spec: dict,
        planner_prompt_template: str,
        director_prompt_template: str,
        provider_credential_secret: str,
        model_name: str | None = None,
    ) -> Tuple[str, dict]:
        """Executes the blocking HTTP call directly — safe to call from any thread."""
        return self._execute_http_call(
            prompt=prompt,
            history=history,
            creation_spec=creation_spec,
            planner_prompt_template=planner_prompt_template,
            director_prompt_template=director_prompt_template,
            provider_credential_secret=provider_credential_secret,
            model_name=model_name,
        )

    def _execute_http_call(
        self,
        *,
        prompt: str,
        history: list[dict[str, str]],
        creation_spec: dict,
        planner_prompt_template: str,
        director_prompt_template: str,
        provider_credential_secret: str,
        model_name: str | None = None,
    ) -> Tuple[str, dict]:
        # Smart model fallback chain optimized for free tier quota
        # Based on rate limits: gemini-3.1-flash-lite has highest quota (15 RPM, 500 RPD)
        model_fallback_chain = [
            "gemini-3.1-flash-lite",     # BEST: Highest quota (15 RPM, 500 RPD), less overload
            "gemini-3.5-flash",          # Fallback 1: Gemini 3.5 (5 RPM, 20 RPD)
            "gemini-2.5-flash-lite",     # Fallback 2: Lite version (10 RPM, 20 RPD)
            "gemini-3-flash-preview",    # Fallback 3: Gemini 3 preview (5 RPM, 20 RPD)
            "gemini-2.5-flash",          # Fallback 4: Original target (may be restricted)
        ]
        
        # If user specifies model, try it first then fallback
        if model_name:
            models_to_try = [model_name] + model_fallback_chain
        else:
            models_to_try = model_fallback_chain
        
        # Apply smart sorting: last successful > least used > available
        models_to_try = _quota_tracker.get_sorted_models(models_to_try)
        
        logger.info(f"Model selection order (after smart sorting): {models_to_try}")
        
        # Try each model in sequence until one works
        last_error = None
        for attempt_model in models_to_try:
            if not _quota_tracker.is_available(attempt_model):
                logger.info(f"Skipping {attempt_model}: quota exhausted or restricted")
                continue
                
            try:
                logger.info(f"Attempting Gemini API call with model: {attempt_model}")
                result = self._try_model(
                    model=attempt_model,
                    prompt=prompt,
                    history=history,
                    creation_spec=creation_spec,
                    planner_prompt_template=planner_prompt_template,
                    director_prompt_template=director_prompt_template,
                    provider_credential_secret=provider_credential_secret,
                )
                # Success! Mark it
                _quota_tracker.mark_success(attempt_model)
                logger.info(f"✓ Success with model: {attempt_model}")
                return result
                
            except (GeminiBadRequestError, GeminiAuthError) as exc:
                # Fatal errors → don't retry with other models
                logger.error(f"Fatal error with {attempt_model}: {exc}")
                raise
            except GeminiServerError as exc:
                # Server error → try next model but don't mark as exhausted
                logger.warning(f"Server error with {attempt_model}: {exc}")
                last_error = exc
                continue
            except GeminiRateLimitError as exc:
                # Rate limit or restricted → mark as exhausted and try next
                error_msg = str(exc).lower()
                if "not available for new users" in error_msg or "restricted" in error_msg:
                    logger.warning(f"Model {attempt_model} restricted for new users")
                    _quota_tracker.mark_restricted(attempt_model)
                elif "503" in error_msg or "unavailable" in error_msg:
                    logger.warning(f"Model {attempt_model} temporarily unavailable (503)")
                    _quota_tracker.mark_quota_exhausted(attempt_model, retry_after_seconds=120)  # 2 min
                else:
                    logger.warning(f"Model {attempt_model} quota exceeded (429)")
                    _quota_tracker.mark_quota_exhausted(attempt_model, retry_after_seconds=300)  # 5 min
                last_error = exc
                continue
            except (GeminiTimeoutError, GeminiConnectionError) as exc:
                # Temporary errors → try next model
                logger.warning(f"Temporary error with {attempt_model}: {exc}")
                last_error = exc
                continue
                
        # All models failed
        if last_error:
            raise last_error
        else:
            raise GeminiServerError("All Gemini models unavailable")

    def _try_model(
        self,
        *,
        model: str,
        prompt: str,
        history: list[dict[str, str]],
        creation_spec: dict,
        planner_prompt_template: str,
        director_prompt_template: str,
        provider_credential_secret: str,
    ) -> Tuple[str, dict]:
        """Try a single model - raises on any error"""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": provider_credential_secret,
        }

        # Build System Instruction
        system_instruction = (
            f"You are VisionFlow Creative AI. Your task is to act as a Video Scene Planner and a Visual Art Director "
            f"to generate vertical short-form video script proposals.\n\n"
            f"--- Planner Rules ---\n{planner_prompt_template}\n\n"
            f"--- Visual Art Director Rules ---\n{director_prompt_template}\n\n"
            f"--- Video Specifications (Canonical Creation Spec) ---\n"
            f"Title: {creation_spec.get('title')}\n"
            f"Brief/Premise: {creation_spec.get('brief')}\n"
            f"Format Profile: {creation_spec.get('format_profile')}\n"
            f"Language: {creation_spec.get('language')}\n"
            f"Voice Actor Preset: {creation_spec.get('voice')}\n"
            f"Caption Subtitle Preset: {creation_spec.get('caption_preset')}\n"
            f"Visual Preset Theme: {creation_spec.get('visual_preset')}\n"
            f"Expected Duration: {creation_spec.get('duration_seconds')} seconds\n"
        )

        # Map history to Gemini content parts
        contents = []
        for turn in history:
            role = "user" if turn["actor"] == "user" else "model"
            contents.append({
                "role": role,
                "parts": [{"text": turn["content"]}]
            })

        # Append new user prompt
        contents.append({
            "role": "user",
            "parts": [{"text": prompt}]
        })

        # Structured Output JSON Schema Definition
        json_schema = {
            "type": "OBJECT",
            "properties": {
                "assistant_message": {
                    "type": "STRING",
                    "description": "Conversation message to display to the user explaining the creative plan or choices."
                },
                "title": {
                    "type": "STRING",
                    "description": "Title of the short video proposal."
                },
                "brief": {
                    "type": "STRING",
                    "description": "A summarized premise of the short video."
                },
                "script": {
                    "type": "STRING",
                    "description": "The complete full narrator reading text script of the short video."
                },
                "scenes": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "narration": {
                                "type": "STRING",
                                "description": "The exact voiceover text or background music description for this scene."
                            },
                            "visual_prompt": {
                                "type": "STRING",
                                "description": "Detailed visual art director details, description of characters, actions, camera angles, lighting, and preset theme."
                            },
                            "duration_seconds": {
                                "type": "INTEGER",
                                "description": "Length of this scene in seconds (minimum 3, maximum 20)."
                            },
                            "transition": {
                                "type": "STRING",
                                "description": "Transition effect: cut, fade, dissolve, zoom_in, zoom_out."
                            },
                            "caption": {
                                "type": "STRING",
                                "description": "On-screen subtitle text overlay caption for this scene."
                            }
                        },
                        "required": ["narration", "visual_prompt", "duration_seconds", "transition", "caption"]
                    }
                }
            },
            "required": ["assistant_message", "title", "brief", "script", "scenes"]
        }

        payload = {
            "contents": contents,
            "systemInstruction": {
                "parts": [{"text": system_instruction}]
            },
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": json_schema,
                "temperature": 0.7,
            }
        }

        # Safe network requests wrapper with quota error and gateway mappings
        try:
            # Sync HTTP call
            res = requests.post(url, headers=headers, json=payload, timeout=self._timeout)

            if res.status_code == 429:
                logger.warning("Gemini API rate limited: HTTP 429")
                raise GeminiRateLimitError("Gemini API rate limit exceeded.")
            elif res.status_code == 503:
                logger.warning(f"Gemini API unavailable (HTTP 503) for model {model}: {res.text}")
                raise GeminiRateLimitError(f"Gemini model {model} temporarily unavailable (503).")
            elif res.status_code == 404:
                error_text = res.text
                if "no longer available to new users" in error_text.lower():
                    logger.warning(f"Model {model} restricted for new users")
                    raise GeminiRateLimitError(f"Model {model} not available for new users")
                logger.error(f"Gemini API Not Found (HTTP 404) for model {model}: {error_text}")
                raise GeminiRateLimitError(f"Model {model} not found or not supported")
            elif res.status_code == 400:
                logger.error(f"Gemini API Bad Request (HTTP 400): {res.text}")
                raise GeminiBadRequestError(f"Malformed schema request or invalid model parameters: {res.text}")
            elif res.status_code == 401 or res.status_code == 403:
                logger.error(f"Gemini API Auth Failure (HTTP {res.status_code}): {res.text}")
                raise GeminiAuthError(f"Failed to authenticate with Gemini API: {res.text}")
            elif res.status_code >= 500:
                logger.error(f"Gemini API Server Error (HTTP {res.status_code}): {res.text}")
                raise GeminiServerError(f"Upstream Gemini Server Error: {res.text}")

            res.raise_for_status()

            response_json = res.json()
            candidates = response_json.get("candidates", [])
            if not candidates:
                raise GeminiResponseError("Empty candidate response returned from Gemini.")

            text_response = candidates[0]["content"]["parts"][0]["text"]
            structured_data = json.loads(text_response)

            # Simple structure validation
            assistant_msg = structured_data.get("assistant_message", "")
            proposal_dict = {
                "title": structured_data.get("title", ""),
                "brief": structured_data.get("brief", ""),
                "script": structured_data.get("script", ""),
                "scenes": structured_data.get("scenes", []),
            }
            return assistant_msg, proposal_dict

        except requests.exceptions.Timeout as exc:
            logger.error("Timeout during Gemini API request")
            raise GeminiTimeoutError("Request to Gemini API timed out.") from exc
        except requests.exceptions.ConnectionError as exc:
            logger.error("Connection error during Gemini API request")
            raise GeminiConnectionError("Failed to connect to Gemini API.") from exc
        except json.JSONDecodeError as exc:
            logger.error("Failed to parse Gemini structured JSON output")
            raise GeminiResponseError("Gemini returned invalid structured output JSON.") from exc


class GeminiRateLimitError(Exception):
    pass

class GeminiBadRequestError(Exception):
    pass

class GeminiAuthError(Exception):
    pass

class GeminiServerError(Exception):
    pass

class GeminiTimeoutError(Exception):
    pass

class GeminiConnectionError(Exception):
    pass

class GeminiResponseError(Exception):
    pass
