"""
Sound notification service for the application.

Provides audio feedback for scan success/failure, mission save, etc.
Uses Windows system sounds via winsound for simplicity.
"""

import winsound
import time
from enum import Enum
from typing import Optional, List, Tuple
from threading import Thread

from src.logger import get_logger

logger = get_logger()


class SoundType(Enum):
    """Available sound notification types."""
    SCAN_START = "scan_start"
    SCAN_SUCCESS = "scan_success"
    SCAN_FAIL = "scan_fail"
    MISSION_ADDED = "mission_added"
    WARNING = "warning"


class SoundService:
    """
    Service for playing notification sounds.

    Uses Windows system sounds for compatibility without external dependencies.
    """

    # Sound sequences: list of (frequency, duration) tuples
    # Scan start: single high beep
    # Scan success: low then high (confirmation)
    # Scan fail/warning: triple low beep
    # Mission added: quick high beep
    SOUND_SEQUENCES = {
        SoundType.SCAN_START: [(1200, 100)],                    # High beep to indicate start
        SoundType.SCAN_SUCCESS: [(600, 100), (1000, 150)],      # Low-high confirmation
        SoundType.SCAN_FAIL: [(400, 150), (400, 150), (400, 150)],  # Triple low warning
        SoundType.MISSION_ADDED: [(1200, 100)],                 # Quick high beep
        SoundType.WARNING: [(400, 150), (400, 150), (400, 150)],    # Triple low warning
    }

    # Pause between beeps in a sequence (ms)
    BEEP_GAP_MS = 50

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
            Thread(target=self._play_sequence, args=(sound_type,), daemon=True).start()
        except Exception as e:
            logger.debug(f"Failed to play sound {sound_type.value}: {e}")

    def _play_sequence(self, sound_type: SoundType) -> None:
        """Internal method to play sound sequence (runs in thread)."""
        try:
            if sound_type in self.SOUND_SEQUENCES:
                sequence = self.SOUND_SEQUENCES[sound_type]
                for i, (frequency, duration) in enumerate(sequence):
                    winsound.Beep(frequency, duration)
                    # Add gap between beeps (except after last one)
                    if i < len(sequence) - 1:
                        time.sleep(self.BEEP_GAP_MS / 1000.0)
            else:
                logger.warning(f"Unknown sound type: {sound_type}")
        except Exception as e:
            # winsound.Beep can fail on systems without PC speaker
            logger.debug(f"Sound playback failed: {e}")

    def play_scan_start(self) -> None:
        """Play scan start sound (high beep)."""
        self.play(SoundType.SCAN_START)

    def play_scan_success(self) -> None:
        """Play scan success sound (low-high)."""
        self.play(SoundType.SCAN_SUCCESS)

    def play_scan_fail(self) -> None:
        """Play scan failure sound (triple low beep)."""
        self.play(SoundType.SCAN_FAIL)

    def play_mission_added(self) -> None:
        """Play mission added sound."""
        self.play(SoundType.MISSION_ADDED)

    def play_warning(self) -> None:
        """Play warning sound (triple low beep)."""
        self.play(SoundType.WARNING)

    # Keep old method name for compatibility
    def play_no_location(self) -> None:
        """Play no location warning sound (triple low beep)."""
        self.play(SoundType.WARNING)


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
