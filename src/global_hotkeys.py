"""
Global hotkey manager using keyboard library.

Provides system-wide keyboard shortcuts that work with fullscreen DirectX games
like Star Citizen by using low-level Windows keyboard hooks (WH_KEYBOARD_LL).
"""

from typing import Callable, Dict, List, Optional
import keyboard

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
        self.modifiers = modifiers
        self.key = key
        self.callback = callback
        self.description = description
        self.hotkey_string = self._build_hotkey_string()

    def _build_hotkey_string(self) -> str:
        """Build hotkey string for keyboard library (e.g., 'shift+print screen')."""
        parts = []

        # Normalize modifier names for keyboard library
        modifier_map = {
            'ctrl': 'ctrl',
            'control': 'ctrl',
            'shift': 'shift',
            'alt': 'alt',
            'win': 'windows',
            'cmd': 'windows',
        }

        for mod in self.modifiers:
            mod_lower = mod.lower()
            parts.append(modifier_map.get(mod_lower, mod_lower))

        # Normalize key name for keyboard library
        key_map = {
            'print_screen': 'print screen',
            'page_up': 'page up',
            'page_down': 'page down',
            'return': 'enter',
            'esc': 'escape',
            'scroll_lock': 'scroll lock',
            'num_lock': 'num lock',
            'caps_lock': 'caps lock',
            'bracket_left': '[',
            'bracket_right': ']',
            'backslash': '\\',
            'semicolon': ';',
            'apostrophe': "'",
            'comma': ',',
            'period': '.',
            'slash': '/',
            'grave': '`',
            'equals': '=',
            'minus': '-',
            'plus': '+',
            'asterisk': '*',
            # Numpad keys
            'num_0': 'num 0',
            'num_1': 'num 1',
            'num_2': 'num 2',
            'num_3': 'num 3',
            'num_4': 'num 4',
            'num_5': 'num 5',
            'num_6': 'num 6',
            'num_7': 'num 7',
            'num_8': 'num 8',
            'num_9': 'num 9',
            'num_minus': 'num -',
            'num_plus': 'num +',
            'num_multiply': 'num *',
            'num_divide': 'num /',
            'num_decimal': 'num .',
            'num_enter': 'num enter',
        }

        key_lower = self.key.lower()
        parts.append(key_map.get(key_lower, key_lower.replace('_', ' ')))

        return '+'.join(parts)


class GlobalHotkeyManager:
    """
    Manages system-wide keyboard shortcuts using the keyboard library.

    Uses low-level Windows hooks (WH_KEYBOARD_LL) that work with fullscreen
    DirectX games like Star Citizen.
    """

    def __init__(self):
        """Initialize the global hotkey manager."""
        self.hotkeys: Dict[str, HotkeyConfig] = {}
        self._running = False
        self._registered_hooks: Dict[str, Callable] = {}

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
        logger.info(f"Registered global hotkey '{name}': {hotkey.hotkey_string} - {description}")

        # If already running, register the hook immediately
        if self._running:
            self._register_hook(name, hotkey)

    def unregister(self, name: str) -> None:
        """Unregister a hotkey by name."""
        if name in self.hotkeys:
            # Remove the hook if it exists
            if name in self._registered_hooks:
                try:
                    keyboard.remove_hotkey(self._registered_hooks[name])
                except (KeyError, ValueError):
                    pass  # Hook might already be removed
                del self._registered_hooks[name]

            del self.hotkeys[name]
            logger.info(f"Unregistered global hotkey: {name}")

    def _register_hook(self, name: str, hotkey: HotkeyConfig) -> None:
        """Register a single hotkey hook with the keyboard library."""
        try:
            # Use suppress=False to allow the key event to pass through to other apps
            hook = keyboard.add_hotkey(
                hotkey.hotkey_string,
                hotkey.callback,
                suppress=False,
                trigger_on_release=False
            )
            self._registered_hooks[name] = hook
            logger.debug(f"Hook registered for '{name}': {hotkey.hotkey_string}")
        except Exception as e:
            logger.error(f"Failed to register hotkey '{name}' ({hotkey.hotkey_string}): {e}")

    def start(self) -> None:
        """Start listening for global hotkeys."""
        if self._running:
            logger.warning("Global hotkey listener already running")
            return

        self._running = True

        # Register all hotkeys
        for name, hotkey in self.hotkeys.items():
            self._register_hook(name, hotkey)

        logger.info(f"Global hotkey listener started with {len(self.hotkeys)} hotkeys")

    def stop(self) -> None:
        """Stop listening for global hotkeys."""
        if not self._running:
            return

        self._running = False

        # Remove all registered hooks
        for name, hook in list(self._registered_hooks.items()):
            try:
                keyboard.remove_hotkey(hook)
            except (KeyError, ValueError):
                pass  # Hook might already be removed

        self._registered_hooks.clear()
        logger.info("Global hotkey listener stopped")

    def get_hotkeys_info(self) -> List[Dict[str, str]]:
        """
        Get information about all registered hotkeys.

        Returns:
            List of dicts with name, keys, and description
        """
        info = []
        for name, hotkey in self.hotkeys.items():
            # Format key combination nicely for display
            modifiers_str = '+'.join(mod.title() for mod in hotkey.modifiers)
            key_str = hotkey.key.replace('_', ' ').title()
            keys = f"{modifiers_str}+{key_str}" if modifiers_str else key_str

            info.append({
                'name': name,
                'keys': keys,
                'description': hotkey.description
            })

        return info
