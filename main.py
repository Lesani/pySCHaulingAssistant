"""
Star Citizen Hauling Assistant - Screen Capture Tool
=====================================================

A desktop utility for capturing screen regions, adjusting images, and sending
them to AI APIs (Anthropic Claude or OpenRouter) to extract structured
Star Citizen hauling mission data.

Features:
- Drag-and-drop region selection
- Screen capture of selected area
- Optional image adjustments (brightness, contrast, gamma)
- Structured data extraction with JSON schema
- Multiple API provider support (Anthropic, OpenRouter)
- Modern PyQt6 interface with dark theme
- Mission management and route optimization
- Configurable via config.json

Usage:
    python main.py

Configuration:
    Edit config.json to customize API endpoints, models, and UI settings.
    Set API keys via environment variables:
    - ANTHROPIC_API_KEY for Anthropic
    - OPENROUTER_API_KEY for OpenRouter
"""

import sys
from PyQt6.QtWidgets import QApplication

from src.logger import AppLogger
from src.config import Config
from src.ui.main_window import MainWindow


def main() -> None:
    """Entry point for the application."""
    # Initialize logger first
    logger = AppLogger.setup(log_level="INFO")
    logger.info("Starting SC Hauling Assistant (PyQt6)")

    try:
        # Load configuration
        config = Config()

        # Create Qt application
        app = QApplication(sys.argv)
        app.setApplicationName("SC Hauling Assistant")
        app.setOrganizationName("SCHaulingAssistant")

        # Create and show main window
        window = MainWindow(config)
        window.show()

        # Run event loop
        logger.info("Application UI initialized, entering main loop")
        sys.exit(app.exec())

    except Exception as e:
        logger.exception(f"Fatal error in main application: {e}")
        raise
    finally:
        logger.info("Application shutting down")
        logger.info("=" * 60)


if __name__ == "__main__":
    main()
