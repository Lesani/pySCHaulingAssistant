"""
API client for communicating with Claude API providers.

Supports both Anthropic's native API and OpenRouter with structured output.
"""

import base64
import io
import json
from typing import Dict, Any, Optional

from PIL import Image
import requests

from src.logger import get_logger

logger = get_logger()


class APIClient:
    """Client for sending images to AI APIs with structured output support."""

    def __init__(self, config) -> None:
        self.config = config

    def extract_mission_data(
        self,
        image: Image.Image,
        api_key: str,
        model: str = None
    ) -> Dict[str, Any]:
        """
        Extract structured hauling mission data from an image.

        Args:
            image: PIL Image to analyze
            api_key: API key for authentication
            model: Optional model override

        Returns:
            Dictionary with mission data or error information
        """
        provider = self.config.get_api_provider()
        logger.info(f"Extracting mission data using provider: {provider}")

        if provider == "anthropic":
            return self._extract_anthropic(image, api_key, model)
        elif provider == "openrouter":
            return self._extract_openrouter(image, api_key, model)
        else:
            error_msg = f"Unknown API provider '{provider}'"
            logger.error(error_msg)
            return {"error": error_msg}

    def _encode_image(self, image: Image.Image) -> str:
        """Encode PIL image as base64 PNG string."""
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        data_bytes = buffer.getvalue()
        return base64.b64encode(data_bytes).decode("utf-8")

    def _get_mission_schema(self) -> Dict[str, Any]:
        """Get the JSON schema for hauling mission data."""
        return {
            "type": "object",
            "properties": {
                "rank": {
                    "type": "string",
                    "description": "Mission rank from the title (e.g., 'Rookie Rank - Small cargo haul' -> 'Rookie', 'Member Rank - Medium cargo haul' -> 'Member'). Valid ranks: Trainee, Rookie, Junior, Member, Experienced, Senior, Master."
                },
                "contracted_by": {
                    "type": "string",
                    "description": "The organization or entity that contracted the mission (e.g., 'Covalex Shipping', 'Red Wind Linehaul'). Usually shown in the mission details."
                },
                "reward": {
                    "type": "number",
                    "description": "Mission reward amount in aUEC"
                },
                "availability": {
                    "type": "string",
                    "description": "Time remaining in HH:MM:SS format (e.g., 01:45:14)"
                },
                "objectives": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "collect_from": {
                                "type": "string",
                                "description": "Location to collect cargo from"
                            },
                            "cargo_type": {
                                "type": "string",
                                "description": "Type of cargo or commodity (e.g., 'Medical Supplies', 'Agricultural Supplies', 'Laranite', 'Quantainium')"
                            },
                            "scu_amount": {
                                "type": "integer",
                                "description": "Target SCU amount to deliver (extract the number from 'X/Y SCU' format, e.g., '0/6 SCU' → 6)"
                            },
                            "deliver_to": {
                                "type": "string",
                                "description": "Location to deliver cargo to"
                            }
                        },
                        "required": ["collect_from", "cargo_type", "scu_amount", "deliver_to"]
                    }
                }
            },
            "required": ["reward", "availability", "objectives"]
        }

    def _get_extraction_prompt(self) -> str:
        """Get the prompt for mission data extraction."""
        return """Extract the Star Citizen hauling mission information from this image.

Please identify:
1. Mission rank from the title (e.g., "Rookie Rank - Small cargo haul" -> "Rookie"). Valid ranks: Trainee, Rookie, Junior, Member, Experienced, Senior, Master. If no rank visible, omit.
2. Contracted by: The organization or entity that contracted the mission (e.g., "Covalex Shipping", "Red Wind Linehaul"). Usually shown in mission details. If not visible, omit.
3. Reward amount (just the number, e.g., 48500)
4. Availability time remaining (convert to HH:MM:SS format, e.g., "1h 45min 14s" becomes "01:45:14". If it shows "N/A" or no time limit, use "N/A")
5. All objectives in the mission, each with:
   - Collect from: The source location name
   - Cargo type: The type of cargo or commodity (e.g., "Medical Supplies", "Agricultural Supplies", "Laranite", "Quantainium")
   - SCU amount: Extract ONLY the target amount number from the "X/Y SCU" format (e.g., "0/6 SCU" -> 6, "0/7 SCU" -> 7)
   - Deliver to: The destination location name (including facility and moon/planet if shown)

IMPORTANT: Return ONLY valid JSON matching the schema. Do not include any explanations or additional text."""

    def _extract_anthropic(
        self,
        image: Image.Image,
        api_key: str,
        model: str = None
    ) -> Dict[str, Any]:
        """Extract mission data using Anthropic's API with structured output."""
        api_config = self.config.get_api_config()

        if model is None:
            model = api_config["default_model"]

        image_base64 = self._encode_image(image)
        schema = self._get_mission_schema()
        prompt = self._get_extraction_prompt()

        # Build request with tool use for structured output
        payload = {
            "model": model,
            "max_tokens": self.config.get("api", "max_tokens", default=1024),
            "tools": [
                {
                    "name": "record_mission_data",
                    "description": "Record the extracted Star Citizen hauling mission data",
                    "input_schema": schema
                }
            ],
            "tool_choice": {"type": "tool", "name": "record_mission_data"},
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": image_base64
                            }
                        },
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ]
                }
            ]
        }

        headers = {
            "x-api-key": api_key,
            "anthropic-version": api_config["api_version"],
            "content-type": "application/json"
        }

        url = api_config["base_url"]

        try:
            logger.debug(f"Sending request to Anthropic API with model: {model}")
            response = requests.post(url, headers=headers, json=payload, timeout=60)
            response.raise_for_status()
            resp_data = response.json()

            # Extract tool use from response
            content_items = resp_data.get("content", [])
            for item in content_items:
                if isinstance(item, dict) and item.get("type") == "tool_use":
                    tool_input = item.get("input", {})
                    logger.info("Successfully extracted mission data from Anthropic API")
                    logger.debug(f"Extracted data: {tool_input}")
                    return {
                        "success": True,
                        "data": tool_input
                    }

            error_msg = "No structured data found in response"
            logger.warning(f"{error_msg}: {resp_data}")
            return {"error": error_msg, "raw": str(resp_data)}

        except requests.exceptions.Timeout:
            error_msg = "Request timed out after 60 seconds"
            logger.error(error_msg)
            return {"error": error_msg}
        except requests.exceptions.RequestException as exc:
            logger.error(f"API request failed: {exc}")
            return {"error": str(exc)}
        except json.JSONDecodeError as exc:
            logger.error(f"JSON decode error: {exc}")
            return {"error": f"JSON decode error: {exc}"}

    def _extract_openrouter(
        self,
        image: Image.Image,
        api_key: str,
        model: str = None
    ) -> Dict[str, Any]:
        """Extract mission data using OpenRouter API."""
        api_config = self.config.get_api_config()

        if model is None:
            model = api_config["default_model"]

        image_base64 = self._encode_image(image)
        prompt = self._get_extraction_prompt()

        # OpenRouter uses OpenAI-compatible format
        # Request JSON response format
        payload = {
            "model": model,
            "max_tokens": self.config.get("api", "max_tokens", default=1024),
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": "You are a Star Citizen mission data extractor. You MUST respond with ONLY valid JSON matching the schema provided. Do not include any explanatory text, markdown formatting, or comments - only the raw JSON object."
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{image_base64}"
                            }
                        },
                        {
                            "type": "text",
                            "text": f"{prompt}\n\nSchema: {json.dumps(self._get_mission_schema(), indent=2)}"
                        }
                    ]
                }
            ]
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/pySCHaulingAssistant",
            "X-Title": "SC Hauling Assistant"
        }

        url = api_config["base_url"]

        try:
            logger.debug(f"Sending request to OpenRouter API with model: {model}")
            response = requests.post(url, headers=headers, json=payload, timeout=60)
            response.raise_for_status()
            resp_data = response.json()

            # Extract JSON from OpenAI-compatible response
            choices = resp_data.get("choices", [])
            if choices:
                message = choices[0].get("message", {})
                content = message.get("content", "")

                try:
                    mission_data = json.loads(content)
                    logger.info("Successfully extracted mission data from OpenRouter API")
                    logger.debug(f"Extracted data: {mission_data}")
                    return {
                        "success": True,
                        "data": mission_data
                    }
                except json.JSONDecodeError as e:
                    # Try to extract JSON from response if it contains other text
                    logger.warning(f"Initial JSON parse failed: {e}")
                    logger.debug(f"Response content (first 500 chars): {content[:500]}")

                    # Try to find JSON object in the response
                    try:
                        # Look for JSON object markers
                        start = content.find('{')
                        end = content.rfind('}') + 1
                        if start >= 0 and end > start:
                            json_str = content[start:end]
                            mission_data = json.loads(json_str)
                            logger.info("Successfully extracted JSON from within response")
                            logger.debug(f"Extracted data: {mission_data}")
                            return {
                                "success": True,
                                "data": mission_data
                            }
                    except (json.JSONDecodeError, ValueError) as e2:
                        logger.error(f"Could not extract JSON from response: {e2}")

                    error_msg = f"Failed to parse JSON response. The model may have returned explanatory text instead of pure JSON."
                    logger.error(f"{error_msg} Original error: {e}")
                    logger.error(f"Response preview: {content[:200]}...")
                    return {"error": error_msg, "raw": content[:1000]}

            error_msg = "No response data from OpenRouter"
            logger.warning(f"{error_msg}: {resp_data}")
            return {"error": error_msg, "raw": str(resp_data)}

        except requests.exceptions.Timeout:
            error_msg = "Request timed out after 60 seconds"
            logger.error(error_msg)
            return {"error": error_msg}
        except requests.exceptions.RequestException as exc:
            logger.error(f"API request failed: {exc}")
            return {"error": str(exc)}
