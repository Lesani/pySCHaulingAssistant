"""
Global hotkey manager using pynput.

Provides system-wide keyboard shortcuts that work regardless of which window is focused.
"""

from typing import Callable, Dict, List, Optional, Set
from threading import Thread
from pynput import keyboard
from pynput.keyboard import Key, KeyCode

from src.logger import get_logger

logger = get_logger()


class HotkeyConfig:
    """Configuration for a single hotkey."""

    def __init__(self, modifiers: List[str], key: str, callback: Callable, description: str = ""):
        """
        Initialize hotkey configuration.

        Args:
            modifiers: List of modifier keys (e.g., ['shift', 'ctrl'])
            key: Main key (e.g., 'print_screen', 'enter', 'a')
            callback: Function to call when hotkey is pressed
            description: Human-readable description
        """
        self.modifiers = self._normalize_modifiers(modifiers)
        self.key = self._normalize_key(key)
        self.callback = callback
        self.description = description

    @staticmethod
    def _normalize_modifiers(modifiers: List[str]) -> Set[Key]:
        """Convert modifier strings to pynput Key objects."""
        modifier_map = {
            'shift': Key.shift,
            'ctrl': Key.ctrl,
            'control': Key.ctrl,
            'alt': Key.alt,
            'cmd': Key.cmd,
            'win': Key.cmd,
        }

        normalized = set()
        for mod in modifiers:
            mod_lower = mod.lower()
            if mod_lower in modifier_map:
                normalized.add(modifier_map[mod_lower])
            else:
                logger.warning(f"Unknown modifier: {mod}")

        return normalized

    @staticmethod
    def _normalize_key(key: str) -> Key | KeyCode:
        """Convert key string to pynput Key or KeyCode object."""
        # Special keys
        special_keys = {
            'print_screen': Key.print_screen,
            'enter': Key.enter,
            'return': Key.enter,
            'space': Key.space,
            'tab': Key.tab,
            'backspace': Key.backspace,
            'delete': Key.delete,
            'esc': Key.esc,
            'escape': Key.esc,
            'up': Key.up,
            'down': Key.down,
            'left': Key.left,
            'right': Key.right,
            'home': Key.home,
            'end': Key.end,
            'page_up': Key.page_up,
            'page_down': Key.page_down,
            'f1': Key.f1, 'f2': Key.f2, 'f3': Key.f3, 'f4': Key.f4,
            'f5': Key.f5, 'f6': Key.f6, 'f7': Key.f7, 'f8': Key.f8,
            'f9': Key.f9, 'f10': Key.f10, 'f11': Key.f11, 'f12': Key.f12,
        }

        key_lower = key.lower()
        if key_lower in special_keys:
            return special_keys[key_lower]

        # Regular character keys
        if len(key) == 1:
            return KeyCode.from_char(key.lower())

        logger.warning(f"Unknown key: {key}, using as character")
        return KeyCode.from_char(key[0].lower())


class GlobalHotkeyManager:
    """Manages system-wide keyboard shortcuts using pynput."""

    def __init__(self):
        """Initialize the global hotkey manager."""
        self.hotkeys: Dict[str, HotkeyConfig] = {}
        self.listener: Optional[keyboard.Listener] = None
        self.current_keys: Set[Key | KeyCode] = set()
        self._running = False

    def register(self, name: str, modifiers: List[str], key: str,
                 callback: Callable, description: str = "") -> None:
        """
        Register a global hotkey.

        Args:
            name: Unique identifier for this hotkey
            modifiers: List of modifier keys (e.g., ['shift', 'ctrl'])
            key: Main key (e.g., 'print_screen', 'enter')
            callback: Function to call when hotkey is pressed
            description: Human-readable description
        """
        hotkey = HotkeyConfig(modifiers, key, callback, description)
        self.hotkeys[name] = hotkey
        logger.info(f"Registered global hotkey '{name}': {modifiers}+{key} - {description}")

    def unregister(self, name: str) -> None:
        """Unregister a hotkey by name."""
        if name in self.hotkeys:
            del self.hotkeys[name]
            logger.info(f"Unregistered global hotkey: {name}")

    def start(self) -> None:
        """Start listening for global hotkeys."""
        if self._running:
            logger.warning("Global hotkey listener already running")
            return

        self._running = True
        self.listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release
        )

        # Start listener in daemon thread
        self.listener.start()
        logger.info("Global hotkey listener started")

    def stop(self) -> None:
        """Stop listening for global hotkeys."""
        if not self._running:
            return

        self._running = False
        if self.listener:
            self.listener.stop()
            self.listener = None

        self.current_keys.clear()
        logger.info("Global hotkey listener stopped")

    def _normalize_key_for_comparison(self, key) -> Key | KeyCode:
        """Normalize key for comparison, handling left/right variants."""
        # Convert left/right variants to generic versions
        if hasattr(key, 'name'):
            if key in (Key.shift_l, Key.shift_r):
                return Key.shift
            elif key in (Key.ctrl_l, Key.ctrl_r):
                return Key.ctrl
            elif key in (Key.alt_l, Key.alt_r):
                return Key.alt
            elif key in (Key.cmd_l, Key.cmd_r):
                return Key.cmd

        # Normalize character keys to lowercase
        if isinstance(key, KeyCode) and key.char:
            return KeyCode.from_char(key.char.lower())

        return key

    def _on_press(self, key) -> None:
        """Handle key press event."""
        normalized_key = self._normalize_key_for_comparison(key)
        self.current_keys.add(normalized_key)

        # Check if any hotkey matches
        self._check_hotkeys()

    def _on_release(self, key) -> None:
        """Handle key release event."""
        normalized_key = self._normalize_key_for_comparison(key)
        self.current_keys.discard(normalized_key)

    def _check_hotkeys(self) -> None:
        """Check if current key combination matches any registered hotkeys."""
        for name, hotkey in self.hotkeys.items():
            # Check if all required modifiers are pressed
            modifiers_pressed = all(
                any(self._normalize_key_for_comparison(k) == mod
                    for k in self.current_keys)
                for mod in hotkey.modifiers
            )

            # Check if the main key is pressed
            key_pressed = any(
                self._normalize_key_for_comparison(k) == hotkey.key
                for k in self.current_keys
            )

            # Check if only the required keys are pressed (no extra modifiers)
            expected_keys = hotkey.modifiers | {hotkey.key}
            actual_keys = {self._normalize_key_for_comparison(k) for k in self.current_keys}

            if modifiers_pressed and key_pressed and expected_keys == actual_keys:
                logger.debug(f"Hotkey triggered: {name}")
                try:
                    # Execute callback in a separate thread to avoid blocking
                    Thread(target=hotkey.callback, daemon=True).start()
                except Exception as e:
                    logger.error(f"Error executing hotkey callback '{name}': {e}")

    def get_hotkeys_info(self) -> List[Dict[str, str]]:
        """
        Get information about all registered hotkeys.

        Returns:
            List of dicts with name, keys, and description
        """
        info = []
        for name, hotkey in self.hotkeys.items():
            # Format key combination nicely
            modifiers_str = '+'.join(str(m).replace('Key.', '').title()
                                    for m in sorted(hotkey.modifiers, key=str))
            key_str = str(hotkey.key).replace('Key.', '').replace('_', ' ').title()
            if isinstance(hotkey.key, KeyCode):
                key_str = hotkey.key.char.upper() if hotkey.key.char else str(hotkey.key)

            keys = f"{modifiers_str}+{key_str}" if modifiers_str else key_str

            info.append({
                'name': name,
                'keys': keys,
                'description': hotkey.description
            })

        return info
