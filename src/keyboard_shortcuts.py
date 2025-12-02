"""
Keyboard shortcuts for the application.

Provides configurable key bindings for common actions.
"""

import tkinter as tk
from typing import Dict, Callable, Optional
from dataclasses import dataclass

from src.logger import get_logger

logger = get_logger()


@dataclass
class Shortcut:
    """Keyboard shortcut definition."""
    key: str
    description: str
    callback: Callable
    enabled: bool = True


class KeyboardShortcuts:
    """Manages keyboard shortcuts for the application."""

    def __init__(self, root: tk.Tk):
        """
        Initialize keyboard shortcuts.

        Args:
            root: Root window
        """
        self.root = root
        self.shortcuts: Dict[str, Shortcut] = {}

        # Register default shortcuts
        self._register_defaults()

    def _register_defaults(self):
        """Register default application shortcuts."""
        # Note: These will be connected to actual callbacks during MainWindow init
        pass

    def register(
        self,
        key: str,
        description: str,
        callback: Callable,
        enabled: bool = True
    ) -> None:
        """
        Register a keyboard shortcut.

        Args:
            key: Key combination (e.g., "<Control-n>", "<F5>")
            description: Human-readable description
            callback: Function to call when shortcut is pressed
            enabled: Whether shortcut is enabled
        """
        self.shortcuts[key] = Shortcut(
            key=key,
            description=description,
            callback=callback,
            enabled=enabled
        )

        # Bind to root window
        self.root.bind(key, lambda event: self._handle_shortcut(key, event))

        logger.debug(f"Registered shortcut: {key} - {description}")

    def _handle_shortcut(self, key: str, event) -> str:
        """
        Handle shortcut key press.

        Args:
            key: Key combination
            event: Tkinter event

        Returns:
            "break" to prevent further propagation
        """
        shortcut = self.shortcuts.get(key)

        if not shortcut or not shortcut.enabled:
            return ""

        try:
            logger.debug(f"Executing shortcut: {key}")
            shortcut.callback()
        except Exception as e:
            logger.error(f"Error executing shortcut {key}: {e}")

        return "break"

    def enable(self, key: str) -> None:
        """Enable a shortcut."""
        if key in self.shortcuts:
            self.shortcuts[key].enabled = True

    def disable(self, key: str) -> None:
        """Disable a shortcut."""
        if key in self.shortcuts:
            self.shortcuts[key].enabled = False

    def get_shortcuts_help(self) -> str:
        """
        Get formatted help text for all shortcuts.

        Returns:
            Multi-line string with shortcut descriptions
        """
        lines = ["KEYBOARD SHORTCUTS", "=" * 50, ""]

        # Group by category
        categories = {
            "General": [],
            "Missions": [],
            "Navigation": [],
        }

        for shortcut in self.shortcuts.values():
            # Categorize based on description keywords
            if any(word in shortcut.description.lower()
                   for word in ["new", "save", "export", "quit"]):
                categories["General"].append(shortcut)
            elif any(word in shortcut.description.lower()
                     for word in ["mission", "delete", "complete"]):
                categories["Missions"].append(shortcut)
            else:
                categories["Navigation"].append(shortcut)

        # Format output
        for category, shortcuts in categories.items():
            if not shortcuts:
                continue

            lines.append(f"{category}:")
            for shortcut in shortcuts:
                # Format key nicely
                key_display = shortcut.key.replace("<", "").replace(">", "")
                key_display = key_display.replace("Control", "Ctrl")
                lines.append(f"  {key_display:20s} - {shortcut.description}")
            lines.append("")

        return "\n".join(lines)


def setup_default_shortcuts(
    root: tk.Tk,
    main_window
) -> KeyboardShortcuts:
    """
    Set up default keyboard shortcuts for the application.

    Args:
        root: Root window
        main_window: MainWindow instance

    Returns:
        KeyboardShortcuts instance
    """
    shortcuts = KeyboardShortcuts(root)

    # Capture & Extract
    shortcuts.register(
        "<F5>",
        "Capture & Extract mission",
        lambda: main_window._capture_and_extract()
    )

    # Refresh views
    shortcuts.register(
        "<Control-r>",
        "Refresh current view",
        lambda: main_window.hauling_tab_widget.refresh()
    )

    # Delete selected
    shortcuts.register(
        "<Delete>",
        "Delete selected mission",
        lambda: main_window.hauling_tab_widget._delete_mission()
    )

    # Export
    shortcuts.register(
        "<Control-e>",
        "Export missions",
        lambda: main_window.hauling_tab_widget._export_missions()
    )

    # Tab navigation
    shortcuts.register(
        "<Control-1>",
        "Switch to Capture tab",
        lambda: main_window.notebook.select(0)
    )

    shortcuts.register(
        "<Control-2>",
        "Switch to Hauling tab",
        lambda: main_window.notebook.select(1)
    )

    shortcuts.register(
        "<Control-3>",
        "Switch to Location tab",
        lambda: main_window.notebook.select(2)
    )

    shortcuts.register(
        "<Control-4>",
        "Switch to Config tab",
        lambda: main_window.notebook.select(3)
    )

    # Help
    shortcuts.register(
        "<F1>",
        "Show keyboard shortcuts help",
        lambda: _show_shortcuts_help(root, shortcuts)
    )

    logger.info("Default keyboard shortcuts registered")
    return shortcuts


def _show_shortcuts_help(root: tk.Tk, shortcuts: KeyboardShortcuts):
    """Show shortcuts help dialog."""
    from tkinter import messagebox

    help_text = shortcuts.get_shortcuts_help()
    messagebox.showinfo("Keyboard Shortcuts", help_text)
