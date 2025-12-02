"""
Sound notification service for the application.

Provides audio feedback for scan success/failure, mission save, etc.
Uses pygame for WAV file playback with fallback to winsound beeps.
"""

import winsound
import time
from enum import Enum
from pathlib import Path
from typing import Optional, Dict
from threading import Thread, Lock

from src.logger import get_logger

logger = get_logger()

# Try to import pygame for WAV playback
_pygame_available = False
try:
    import pygame
    import pygame.mixer
    _pygame_available = True
except ImportError:
    logger.warning("pygame not available, falling back to winsound beeps")


class SoundType(Enum):
    """Available sound notification types."""
    SCAN_START = "scan_start"
    SCAN_SUCCESS = "scan_success"
    SCAN_FAIL = "scan_fail"
    MISSION_ADDED = "mission_added"
    WARNING = "warning"
    ROUTE_COMPLETE = "route_complete"
    SYNC_COMPLETE = "sync_complete"


class SoundService:
    """
    Service for playing notification sounds.

    Uses WAV files via pygame when available, with fallback to winsound beeps.
    """

    # Fallback sound sequences: list of (frequency, duration) tuples
    FALLBACK_SEQUENCES = {
        SoundType.SCAN_START: [(1200, 100)],
        SoundType.SCAN_SUCCESS: [(600, 100), (1000, 150)],
        SoundType.SCAN_FAIL: [(400, 150), (400, 150), (400, 150)],
        SoundType.MISSION_ADDED: [(1200, 100)],
        SoundType.WARNING: [(400, 150), (400, 150), (400, 150)],
        SoundType.ROUTE_COMPLETE: [(800, 100), (1000, 100), (1200, 200)],
        SoundType.SYNC_COMPLETE: [(1000, 100), (1200, 150)],
    }

    # Pause between beeps in a sequence (ms)
    BEEP_GAP_MS = 50

    def __init__(self, enabled: bool = True, volume: float = 0.7):
        """
        Initialize sound service.

        Args:
            enabled: Whether sounds are enabled
            volume: Volume level from 0.0 to 1.0
        """
        self._enabled = enabled
        self._volume = max(0.0, min(1.0, volume))
        self._initialized = False
        # sounds/ folder is at project root (parent of src/)
        self._sounds_dir = Path(__file__).parent.parent / "sounds"
        self._sound_cache: Dict[SoundType, pygame.mixer.Sound] = {}
        self._play_lock = Lock()

        # Initialize pygame mixer if available
        if _pygame_available and enabled:
            self._init_audio()

    def _init_audio(self) -> None:
        """Initialize pygame mixer for WAV playback."""
        try:
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
            self._initialized = True
            self._load_sounds()
            logger.info("Sound system initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize sound system: {e}")
            self._initialized = False

    def _load_sounds(self) -> None:
        """Load WAV files into memory for fast playback."""
        for sound_type in SoundType:
            wav_file = self._sounds_dir / f"{sound_type.value}.wav"
            if wav_file.exists():
                try:
                    sound = pygame.mixer.Sound(str(wav_file))
                    sound.set_volume(self._volume)
                    self._sound_cache[sound_type] = sound
                    logger.debug(f"Loaded sound: {wav_file.name}")
                except Exception as e:
                    logger.warning(f"Failed to load {wav_file.name}: {e}")

    @property
    def enabled(self) -> bool:
        """Check if sounds are enabled."""
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        """Enable or disable sounds."""
        self._enabled = value
        if value and _pygame_available and not self._initialized:
            self._init_audio()
        logger.info(f"Sound notifications {'enabled' if value else 'disabled'}")

    @property
    def volume(self) -> float:
        """Get current volume level."""
        return self._volume

    @volume.setter
    def volume(self, value: float):
        """Set volume level (0.0 to 1.0)."""
        self._volume = max(0.0, min(1.0, value))
        # Update volume on all cached sounds
        for sound in self._sound_cache.values():
            try:
                sound.set_volume(self._volume)
            except Exception:
                pass
        logger.debug(f"Sound volume set to {self._volume:.0%}")

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
        with self._play_lock:
            # Try WAV first
            if self._initialized and sound_type in self._sound_cache:
                try:
                    sound = self._sound_cache[sound_type]
                    sound.play()
                    return
                except Exception as e:
                    logger.debug(f"WAV playback failed for {sound_type.value}: {e}")

            # Fallback to winsound beeps
            self._play_fallback(sound_type)

    def _play_fallback(self, sound_type: SoundType) -> None:
        """Play fallback beep sounds."""
        try:
            if sound_type in self.FALLBACK_SEQUENCES:
                sequence = self.FALLBACK_SEQUENCES[sound_type]
                for i, (frequency, duration) in enumerate(sequence):
                    winsound.Beep(frequency, duration)
                    if i < len(sequence) - 1:
                        time.sleep(self.BEEP_GAP_MS / 1000.0)
        except Exception as e:
            logger.debug(f"Fallback sound playback failed: {e}")

    def stop(self) -> None:
        """Stop all currently playing sounds."""
        if self._initialized:
            try:
                pygame.mixer.stop()
            except Exception:
                pass

    def play_scan_start(self) -> None:
        """Play scan start sound."""
        self.play(SoundType.SCAN_START)

    def play_scan_success(self) -> None:
        """Play scan success sound."""
        self.play(SoundType.SCAN_SUCCESS)

    def play_scan_fail(self) -> None:
        """Play scan failure sound."""
        self.play(SoundType.SCAN_FAIL)

    def play_mission_added(self) -> None:
        """Play mission added sound."""
        self.play(SoundType.MISSION_ADDED)

    def play_warning(self) -> None:
        """Play warning sound."""
        self.play(SoundType.WARNING)

    def play_route_complete(self) -> None:
        """Play route complete sound."""
        self.play(SoundType.ROUTE_COMPLETE)

    def play_sync_complete(self) -> None:
        """Play sync complete sound."""
        self.play(SoundType.SYNC_COMPLETE)

    # Keep old method name for compatibility
    def play_no_location(self) -> None:
        """Play no location warning sound."""
        self.play(SoundType.WARNING)

    def cleanup(self) -> None:
        """Clean up resources."""
        if self._initialized:
            try:
                self._sound_cache.clear()
                pygame.mixer.quit()
            except Exception:
                pass
            self._initialized = False


# Global instance for easy access
_sound_service: Optional[SoundService] = None


def get_sound_service() -> SoundService:
    """Get the global sound service instance."""
    global _sound_service
    if _sound_service is None:
        _sound_service = SoundService(enabled=True)
    return _sound_service


def init_sound_service(enabled: bool = True, volume: float = 0.7) -> SoundService:
    """Initialize the global sound service with settings."""
    global _sound_service
    _sound_service = SoundService(enabled=enabled, volume=volume)
    return _sound_service


def cleanup_sound_service() -> None:
    """Clean up the global sound service."""
    global _sound_service
    if _sound_service is not None:
        _sound_service.cleanup()
        _sound_service = None
