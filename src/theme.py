"""
Theme management with dark/light mode support.

Uses system preferences and allows manual override.
"""

import tkinter as tk
from tkinter import ttk
from typing import Dict, Any
import darkdetect

from src.logger import get_logger

logger = get_logger()


class Theme:
    """Theme color definitions."""

    DARK = {
        "bg": "#1e1e1e",
        "fg": "#ffffff",
        "bg_secondary": "#2d2d2d",
        "bg_hover": "#3d3d3d",
        "accent": "#0078d4",
        "accent_hover": "#106ebe",
        "success": "#4caf50",
        "warning": "#ff9800",
        "error": "#f44336",
        "text_primary": "#ffffff",
        "text_secondary": "#b0b0b0",
        "border": "#404040",
        "input_bg": "#2d2d2d",
        "button_bg": "#0078d4",
        "button_fg": "#ffffff",
    }

    LIGHT = {
        "bg": "#f5f5f5",
        "fg": "#000000",
        "bg_secondary": "#ffffff",
        "bg_hover": "#e0e0e0",
        "accent": "#0078d4",
        "accent_hover": "#106ebe",
        "success": "#4caf50",
        "warning": "#ff9800",
        "error": "#f44336",
        "text_primary": "#000000",
        "text_secondary": "#666666",
        "border": "#d0d0d0",
        "input_bg": "#ffffff",
        "button_bg": "#0078d4",
        "button_fg": "#ffffff",
    }


class ThemeManager:
    """Manages application theming."""

    def __init__(self, config=None):
        """
        Initialize theme manager.

        Args:
            config: Config instance for saving preferences
        """
        self.config = config
        self.current_theme = "dark"
        self._load_preference()

    def _load_preference(self):
        """Load theme preference from config or system."""
        if self.config:
            saved_theme = self.config.get("ui", "theme")
            if saved_theme in ("dark", "light", "auto"):
                if saved_theme == "auto":
                    self.current_theme = self._detect_system_theme()
                else:
                    self.current_theme = saved_theme
                return

        # Default to system theme
        self.current_theme = self._detect_system_theme()

    def _detect_system_theme(self) -> str:
        """Detect system theme preference."""
        try:
            is_dark = darkdetect.isDark()
            return "dark" if is_dark else "light"
        except Exception as e:
            logger.warning(f"Could not detect system theme: {e}, defaulting to dark")
            return "dark"

    def get_colors(self) -> Dict[str, str]:
        """Get current theme colors."""
        return Theme.DARK if self.current_theme == "dark" else Theme.LIGHT

    def set_theme(self, theme: str):
        """
        Set theme manually.

        Args:
            theme: "dark", "light", or "auto"
        """
        if theme == "auto":
            self.current_theme = self._detect_system_theme()
        elif theme in ("dark", "light"):
            self.current_theme = theme
        else:
            logger.warning(f"Invalid theme: {theme}")
            return

        # Save preference
        if self.config:
            if "ui" not in self.config.settings:
                self.config.settings["ui"] = {}
            self.config.settings["ui"]["theme"] = theme
            self.config.save()

        logger.info(f"Theme set to: {theme} (active: {self.current_theme})")

    def apply_to_window(self, root: tk.Tk):
        """
        Apply theme to tkinter window.

        Args:
            root: Root window
        """
        colors = self.get_colors()

        # Configure main window
        root.configure(bg=colors["bg"])

        # Configure ttk styles
        style = ttk.Style()

        # Frame
        style.configure("TFrame", background=colors["bg"])

        # Label
        style.configure("TLabel",
                       background=colors["bg"],
                       foreground=colors["text_primary"])

        # Button
        style.configure("TButton",
                       background=colors["button_bg"],
                       foreground=colors["button_fg"],
                       borderwidth=0,
                       focuscolor=colors["accent"])

        style.map("TButton",
                 background=[("active", colors["accent_hover"])])

        # Entry
        style.configure("TEntry",
                       fieldbackground=colors["input_bg"],
                       foreground=colors["text_primary"],
                       bordercolor=colors["border"])

        # LabelFrame
        style.configure("TLabelframe",
                       background=colors["bg"],
                       foreground=colors["text_primary"])
        style.configure("TLabelframe.Label",
                       background=colors["bg"],
                       foreground=colors["text_primary"])

        # Notebook (tabs)
        style.configure("TNotebook",
                       background=colors["bg"],
                       borderwidth=0)
        style.configure("TNotebook.Tab",
                       background=colors["bg_secondary"],
                       foreground=colors["text_primary"],
                       padding=[10, 5])
        style.map("TNotebook.Tab",
                 background=[("selected", colors["bg"])],
                 foreground=[("selected", colors["accent"])])

        # Treeview
        style.configure("Treeview",
                       background=colors["input_bg"],
                       foreground=colors["text_primary"],
                       fieldbackground=colors["input_bg"],
                       borderwidth=0)
        style.configure("Treeview.Heading",
                       background=colors["bg_secondary"],
                       foreground=colors["text_primary"],
                       borderwidth=1,
                       relief="flat")
        style.map("Treeview",
                 background=[("selected", colors["accent"])],
                 foreground=[("selected", colors["button_fg"])])

        # Combobox
        style.configure("TCombobox",
                       fieldbackground=colors["input_bg"],
                       background=colors["input_bg"],
                       foreground=colors["text_primary"],
                       arrowcolor=colors["text_primary"],
                       bordercolor=colors["border"])

        logger.debug(f"Applied {self.current_theme} theme to window")

    def get_urgency_color(self, urgency_level: int) -> str:
        """
        Get color for mission urgency level.

        Args:
            urgency_level: 1-5 (1=critical, 5=no limit)

        Returns:
            Color hex string
        """
        colors = self.get_colors()

        if urgency_level == 1:
            return colors["error"]
        elif urgency_level == 2:
            return colors["warning"]
        elif urgency_level == 3:
            return "#ffc107"  # Amber
        else:
            return colors["success"]
