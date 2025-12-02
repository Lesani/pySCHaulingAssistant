"""
Window state persistence for saving and restoring UI state.

Saves window geometry, position, and user preferences.
"""

import json
import os
import tkinter as tk
from typing import Dict, Any, Optional

from src.logger import get_logger

logger = get_logger()


class WindowState:
    """Manages window state persistence."""

    def __init__(self, state_file: str = "window_state.json"):
        """
        Initialize window state manager.

        Args:
            state_file: Path to state file
        """
        self.state_file = state_file
        self.state: Dict[str, Any] = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        """Load state from file."""
        if not os.path.exists(self.state_file):
            return self._get_defaults()

        try:
            with open(self.state_file, 'r') as f:
                state = json.load(f)
            logger.debug(f"Loaded window state from {self.state_file}")
            return state
        except Exception as e:
            logger.warning(f"Failed to load window state: {e}, using defaults")
            return self._get_defaults()

    def _get_defaults(self) -> Dict[str, Any]:
        """Get default state values."""
        return {
            "window": {
                "width": 900,
                "height": 700,
                "x": None,  # Center on screen
                "y": None
            },
            "tabs": {
                "last_active": 0
            },
            "preferences": {
                "auto_refresh": True,
                "show_completed": False,
                "default_sort": "reward"
            }
        }

    def save(self):
        """Save current state to file."""
        try:
            with open(self.state_file, 'w') as f:
                json.dump(self.state, f, indent=2)
            logger.debug(f"Saved window state to {self.state_file}")
        except Exception as e:
            logger.error(f"Failed to save window state: {e}")

    def apply_to_window(self, root: tk.Tk):
        """
        Apply saved state to window.

        Args:
            root: Root window
        """
        window_state = self.state.get("window", {})

        width = window_state.get("width", 900)
        height = window_state.get("height", 700)
        x = window_state.get("x")
        y = window_state.get("y")

        if x is not None and y is not None:
            # Restore previous position
            root.geometry(f"{width}x{height}+{x}+{y}")
        else:
            # Center on screen
            screen_width = root.winfo_screenwidth()
            screen_height = root.winfo_screenheight()
            x = (screen_width - width) // 2
            y = (screen_height - height) // 2
            root.geometry(f"{width}x{height}+{x}+{y}")

        logger.debug(f"Applied window geometry: {width}x{height}+{x}+{y}")

    def capture_window_geometry(self, root: tk.Tk):
        """
        Capture current window geometry.

        Args:
            root: Root window
        """
        # Get geometry string (e.g., "900x700+100+50")
        geometry = root.geometry()

        try:
            # Parse geometry string
            size, position = geometry.split('+', 1)
            width, height = map(int, size.split('x'))
            x, y = map(int, position.split('+'))

            self.state["window"] = {
                "width": width,
                "height": height,
                "x": x,
                "y": y
            }

            logger.debug(f"Captured window geometry: {geometry}")

        except Exception as e:
            logger.warning(f"Failed to parse geometry: {e}")

    def get_last_active_tab(self) -> int:
        """Get last active tab index."""
        return self.state.get("tabs", {}).get("last_active", 0)

    def set_last_active_tab(self, tab_index: int):
        """Set last active tab index."""
        if "tabs" not in self.state:
            self.state["tabs"] = {}
        self.state["tabs"]["last_active"] = tab_index

    def get_preference(self, key: str, default: Any = None) -> Any:
        """
        Get a user preference.

        Args:
            key: Preference key
            default: Default value if not found

        Returns:
            Preference value
        """
        return self.state.get("preferences", {}).get(key, default)

    def set_preference(self, key: str, value: Any):
        """
        Set a user preference.

        Args:
            key: Preference key
            value: Preference value
        """
        if "preferences" not in self.state:
            self.state["preferences"] = {}
        self.state["preferences"][key] = value

    def on_window_close(self, root: tk.Tk, notebook: Optional[tk.Widget] = None):
        """
        Handler for window close event.

        Captures state before closing.

        Args:
            root: Root window
            notebook: Notebook widget for tab state
        """
        # Capture window geometry
        self.capture_window_geometry(root)

        # Capture active tab
        if notebook:
            try:
                active_tab = notebook.index(notebook.select())
                self.set_last_active_tab(active_tab)
            except:
                pass

        # Save state
        self.save()

        logger.info("Window state saved on close")


def setup_window_state(root: tk.Tk, notebook: Optional[tk.Widget] = None) -> WindowState:
    """
    Set up window state management.

    Args:
        root: Root window
        notebook: Optional notebook widget

    Returns:
        WindowState instance
    """
    window_state = WindowState()

    # Apply saved state
    window_state.apply_to_window(root)

    # Set up close handler
    root.protocol("WM_DELETE_WINDOW", lambda: _on_closing(root, window_state, notebook))

    return window_state


def _on_closing(root: tk.Tk, window_state: WindowState, notebook: Optional[tk.Widget]):
    """Handle window closing."""
    window_state.on_window_close(root, notebook)
    root.destroy()
