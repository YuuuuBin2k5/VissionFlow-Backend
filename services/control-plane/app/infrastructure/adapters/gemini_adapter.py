from __future__ import annotations

import json
import logging
import requests
from typing import Tuple, List, Dict

from app.application.ports.creative_planning_provider import CreativePlanningProvider

logger = logging.getLogger(__name__)


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
        # Enforce Gemini 1.5 Flash as standard planning model
        model = model_name or "gemini-1.5-flash"
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
