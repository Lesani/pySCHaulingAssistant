"""
Sound notification service for the application.

Provides audio feedback for scan success/failure, mission save, etc.
Uses Windows system sounds via winsound for simplicity.
"""

import winsound
from enum import Enum
from typing import Optional
from threading import Thread

from src.logger import get_logger

logger = get_logger()


class SoundType(Enum):
    """Available sound notification types."""
    SCAN_SUCCESS = "scan_success"
    SCAN_FAIL = "scan_fail"
    MISSION_ADDED = "mission_added"
    NO_LOCATION = "no_location"


class SoundService:
    """
    Service for playing notification sounds.

    Uses Windows system sounds for compatibility without external dependencies.
    """

    # Windows system sound mappings
    # See: https://docs.python.org/3/library/winsound.html
    SOUND_MAP = {
        SoundType.SCAN_SUCCESS: (1000, 150),      # 1000Hz for 150ms - pleasant beep
        SoundType.SCAN_FAIL: (400, 300),          # 400Hz for 300ms - low warning tone
        SoundType.MISSION_ADDED: (1200, 100),     # 1200Hz for 100ms - quick high beep
        SoundType.NO_LOCATION: (600, 200),        # 600Hz for 200ms - medium warning
    }

    def __init__(self, enabled: bool = True):
        """
        Initialize sound service.

        Args:
            enabled: Whether sounds are enabled
        """
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        """Check if sounds are enabled."""
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        """Enable or disable sounds."""
        self._enabled = value
        logger.info(f"Sound notifications {'enabled' if value else 'disabled'}")

    def play(self, sound_type: SoundType) -> None:
        """
        Play a notification sound.

        Args:
            sound_type: Type of sound to play
        """
        if not self._enabled:
            return

        try:
            # Play in background thread to avoid blocking UI
            Thread(target=self._play_sound, args=(sound_type,), daemon=True).start()
        except Exception as e:
            logger.debug(f"Failed to play sound {sound_type.value}: {e}")

    def _play_sound(self, sound_type: SoundType) -> None:
        """Internal method to play sound (runs in thread)."""
        try:
            if sound_type in self.SOUND_MAP:
                frequency, duration = self.SOUND_MAP[sound_type]
                winsound.Beep(frequency, duration)
            else:
                logger.warning(f"Unknown sound type: {sound_type}")
        except Exception as e:
            # winsound.Beep can fail on systems without PC speaker
            logger.debug(f"Sound playback failed: {e}")

    def play_scan_success(self) -> None:
        """Play scan success sound."""
        self.play(SoundType.SCAN_SUCCESS)

    def play_scan_fail(self) -> None:
        """Play scan failure sound."""
        self.play(SoundType.SCAN_FAIL)

    def play_mission_added(self) -> None:
        """Play mission added sound."""
        self.play(SoundType.MISSION_ADDED)

    def play_no_location(self) -> None:
        """Play no location warning sound."""
        self.play(SoundType.NO_LOCATION)


# Global instance for easy access
_sound_service: Optional[SoundService] = None


def get_sound_service() -> SoundService:
    """Get the global sound service instance."""
    global _sound_service
    if _sound_service is None:
        _sound_service = SoundService(enabled=True)
    return _sound_service


def init_sound_service(enabled: bool = True) -> SoundService:
    """Initialize the global sound service with settings."""
    global _sound_service
    _sound_service = SoundService(enabled=enabled)
    return _sound_service
