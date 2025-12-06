"""
Configuration management for the application.

Handles loading configuration from config.json and environment variables.
"""

import json
import os
from typing import Dict, Any

from src.logger import get_logger

logger = get_logger()


class Config:
    """Application configuration manager."""

    def __init__(self, config_file: str = "config.json") -> None:
        self.config_file = config_file
        self.settings = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from file and merge with defaults."""
        defaults = {
            "api": {
                "provider": "openrouter",  # "anthropic" or "openrouter"
                "anthropic": {
                    "base_url": "https://api.anthropic.com/v1/messages",
                    "default_model": "claude-sonnet-4-5",
                    "api_version": "2023-06-01"
                },
                "openrouter": {
                    "base_url": "https://openrouter.ai/api/v1/chat/completions",
                    "default_model": "qwen/qwen3-vl-8b-instruct"
                },
                "max_tokens": 512
            },
            "ui": {
                "canvas_height": 400,
                "window_title": "Mission Objective Screen Capture",
                "auto_switch_to_hauling": True
            },
            "image": {
                "default_brightness": 1.0,
                "default_contrast": 1.0,
                "default_gamma": 1.0,
                "slider_min": 0.1,
                "slider_max": 3.0
            },
            "prompts": {
                "mission_analysis": "Identify the objectives of the star citizen mission in this image."
            },
            "capture": {
                "saved_region": None
            }
        }

        # Try to load from file if it exists
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    file_config = json.load(f)
                    # Merge file config with defaults (file config takes precedence)
                    defaults = self._deep_merge(defaults, file_config)
                    logger.info(f"Loaded configuration from {self.config_file}")
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Could not load config file: {e}, using defaults")

        return defaults

    def _deep_merge(self, base: Dict, override: Dict) -> Dict:
        """Recursively merge two dictionaries."""
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    def get_api_key(self) -> str:
        """Get API key from config file or environment variable."""
        # First check config file
        stored_key = self.settings.get("api", {}).get("api_key", "")
        if stored_key:
            return stored_key

        # Fall back to environment variable
        provider = self.settings["api"]["provider"]
        if provider == "anthropic":
            return os.environ.get("ANTHROPIC_API_KEY", "")
        elif provider == "openrouter":
            return os.environ.get("OPENROUTER_API_KEY", "")
        return ""

    def get_api_provider(self) -> str:
        """Get the current API provider."""
        return self.settings["api"]["provider"]

    def get_api_config(self) -> Dict[str, Any]:
        """Get configuration for the current API provider."""
        provider = self.get_api_provider()
        return self.settings["api"][provider]

    def get(self, *keys: str, default: Any = None) -> Any:
        """
        Get a configuration value using a path of keys.

        Example: config.get("api", "anthropic", "default_model")
        """
        result = self.settings
        for key in keys:
            if isinstance(result, dict) and key in result:
                result = result[key]
            else:
                return default
        return result

    def set(self, *keys: str, value: Any) -> None:
        """
        Set a configuration value using a path of keys.

        Example: config.set("api", "max_tokens", 2048)

        Note: Creates nested dictionaries if they don't exist.
        Does NOT auto-save - call save() explicitly.
        """
        if len(keys) == 0:
            raise ValueError("At least one key is required")

        # Navigate to the parent dictionary
        current = self.settings
        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            elif not isinstance(current[key], dict):
                # Can't navigate further - overwrite with dict
                current[key] = {}
            current = current[key]

        # Set the final value
        current[keys[-1]] = value

    def save(self) -> None:
        """Save current configuration to file."""
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=2)
            logger.debug(f"Configuration saved to {self.config_file}")
        except IOError as e:
            logger.error(f"Error saving config file: {e}")

    def get_synergy_enabled(self) -> bool:
        """Check if synergy analysis is enabled."""
        return self.get("synergy", "enabled", default=True)

    def get_capacity_warning_threshold(self) -> float:
        """Get the capacity warning threshold percentage."""
        return self.get("synergy", "capacity_warning_threshold", default=80.0)

    def get_low_synergy_threshold(self) -> float:
        """Get the low synergy score threshold."""
        return self.get("synergy", "low_synergy_threshold", default=30.0)

    def get_synergy_show_recommendations(self) -> bool:
        """Check if synergy recommendations should be shown."""
        return self.get("synergy", "show_recommendations", default=True)

    def get_synergy_check_timing(self) -> bool:
        """Check if timing feasibility should be checked."""
        return self.get("synergy", "check_timing", default=True)

    def get_synergy_show_route_preview(self) -> bool:
        """Check if route preview button should be shown."""
        return self.get("synergy", "show_route_preview", default=True)

    def get_ship_capacity(self) -> float:
        """Get the configured ship capacity in SCU."""
        return self.get("route_planner", "ship_capacity", default=128.0)

    def get_route_finder_thread_count(self) -> int:
        """Get the number of threads for route finder parallel processing."""
        return self.get("route_finder", "thread_count", default=8)

    def get_route_finder_worker_timeout(self) -> int:
        """Get the timeout in seconds for route finder worker tasks."""
        return self.get("route_finder", "worker_timeout", default=30)
