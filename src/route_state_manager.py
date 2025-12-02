"""
Route State Manager for persistence.

Handles saving and loading route state to/from JSON file.
"""

import json
import os
from typing import Optional
from filelock import FileLock

from src.route_state import RouteState
from src.logger import get_logger

logger = get_logger()


class RouteStateManager:
    """Manages route state persistence to route_state.json."""

    def __init__(self, storage_file: str = "route_state.json"):
        """
        Initialize route state manager.

        Args:
            storage_file: Path to route state JSON file
        """
        self.storage_file = storage_file
        self.lock_file = storage_file + ".lock"
        self.route_state: Optional[RouteState] = None

    def load(self) -> RouteState:
        """
        Load route state from file.

        Returns:
            RouteState object (new if file doesn't exist)
        """
        if not os.path.exists(self.storage_file):
            logger.info("No saved route state found, creating new")
            self.route_state = RouteState()
            return self.route_state

        try:
            with FileLock(self.lock_file, timeout=5):
                with open(self.storage_file, 'r') as f:
                    data = json.load(f)
                    self.route_state = RouteState.from_dict(data)
                    logger.info(f"Loaded route state: {len(self.route_state.completed_stop_ids)} completed stops, "
                               f"{self.route_state.cargo_state.current_scu} SCU loaded")
        except Exception as e:
            logger.error(f"Failed to load route state: {e}")
            self.route_state = RouteState()

        return self.route_state

    def save(self, route_state: Optional[RouteState] = None) -> bool:
        """
        Save route state to file.

        Args:
            route_state: RouteState to save (uses self.route_state if None)

        Returns:
            True if saved successfully
        """
        if route_state is None:
            route_state = self.route_state

        if route_state is None:
            logger.warning("No route state to save")
            return False

        try:
            with FileLock(self.lock_file, timeout=5):
                with open(self.storage_file, 'w') as f:
                    json.dump(route_state.to_dict(), f, indent=2)
                logger.debug(f"Route state saved: {len(route_state.completed_stop_ids)} completed stops")
            return True
        except Exception as e:
            logger.error(f"Failed to save route state: {e}")
            return False

    def clear(self) -> bool:
        """
        Clear route state (reset and save empty state).

        Returns:
            True if cleared successfully
        """
        self.route_state = RouteState()
        return self.save()

    def get_state(self) -> RouteState:
        """
        Get current route state (load if not loaded).

        Returns:
            RouteState object
        """
        if self.route_state is None:
            return self.load()
        return self.route_state

    def update_state(self, route_state: RouteState, auto_save: bool = True) -> None:
        """
        Update current route state.

        Args:
            route_state: New route state
            auto_save: Whether to automatically save to file
        """
        self.route_state = route_state
        if auto_save:
            self.save()
