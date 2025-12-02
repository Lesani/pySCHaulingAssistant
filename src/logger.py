"""
Centralized logging configuration for the application.

Provides consistent logging across all modules with file and console output.
"""

import logging
import os
from datetime import datetime
from typing import Optional


class AppLogger:
    """Application logger with file and console handlers."""

    _initialized = False
    _logger: Optional[logging.Logger] = None

    @classmethod
    def setup(cls, log_level: str = "INFO", log_dir: str = "logs") -> logging.Logger:
        """
        Set up the application logger.

        Args:
            log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            log_dir: Directory to store log files

        Returns:
            Configured logger instance
        """
        if cls._initialized:
            return cls._logger

        # Create log directory if it doesn't exist
        os.makedirs(log_dir, exist_ok=True)

        # Create logger
        logger = logging.getLogger("SCHaulingAssistant")
        logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

        # Prevent duplicate handlers
        if logger.handlers:
            logger.handlers.clear()

        # Console handler (INFO and above)
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter(
            '%(levelname)s: %(message)s'
        )
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)

        # File handler (DEBUG and above)
        log_filename = os.path.join(
            log_dir,
            f"sc_hauling_{datetime.now().strftime('%Y%m%d')}.log"
        )
        file_handler = logging.FileHandler(log_filename, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

        cls._logger = logger
        cls._initialized = True

        logger.info("=" * 60)
        logger.info("SC Hauling Assistant Started")
        logger.info("=" * 60)

        return logger

    @classmethod
    def get_logger(cls) -> logging.Logger:
        """
        Get the application logger.

        Returns:
            Logger instance (initializes with defaults if not already set up)
        """
        if not cls._initialized:
            return cls.setup()
        return cls._logger


# Convenience function for getting logger
def get_logger() -> logging.Logger:
    """Get the application logger."""
    return AppLogger.get_logger()
