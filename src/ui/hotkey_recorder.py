"""
Hotkey recorder widget for PyQt6.

A clickable text field that records key combinations like game key bindings.
"""

from PyQt6.QtWidgets import QLineEdit
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent, QFocusEvent

from typing import List, Tuple


class HotkeyRecorder(QLineEdit):
    """
    A text field that records key combinations when focused and a key is pressed.

    Click on the field, then press the desired key combination (e.g., Shift+F5).
    The combination is recorded and displayed.
    """

    # Emitted when a new hotkey is recorded: (modifiers_list, key_name)
    hotkey_changed = pyqtSignal(list, str)

    # Modifier key codes
    MODIFIER_KEYS = {
        Qt.Key.Key_Control: 'ctrl',
        Qt.Key.Key_Shift: 'shift',
        Qt.Key.Key_Alt: 'alt',
        Qt.Key.Key_Meta: 'win',
    }

    # Internal key names (for config storage)
    KEY_INTERNAL_NAMES = {
        # Navigation keys
        Qt.Key.Key_Print: 'print_screen',
        Qt.Key.Key_Return: 'enter',
        Qt.Key.Key_Enter: 'num_enter',
        Qt.Key.Key_Space: 'space',
        Qt.Key.Key_Escape: 'escape',
        Qt.Key.Key_Tab: 'tab',
        Qt.Key.Key_Backspace: 'backspace',
        Qt.Key.Key_Delete: 'delete',
        Qt.Key.Key_Insert: 'insert',
        Qt.Key.Key_Home: 'home',
        Qt.Key.Key_End: 'end',
        Qt.Key.Key_PageUp: 'page_up',
        Qt.Key.Key_PageDown: 'page_down',
        Qt.Key.Key_Up: 'up',
        Qt.Key.Key_Down: 'down',
        Qt.Key.Key_Left: 'left',
        Qt.Key.Key_Right: 'right',
        # Function keys
        Qt.Key.Key_F1: 'f1',
        Qt.Key.Key_F2: 'f2',
        Qt.Key.Key_F3: 'f3',
        Qt.Key.Key_F4: 'f4',
        Qt.Key.Key_F5: 'f5',
        Qt.Key.Key_F6: 'f6',
        Qt.Key.Key_F7: 'f7',
        Qt.Key.Key_F8: 'f8',
        Qt.Key.Key_F9: 'f9',
        Qt.Key.Key_F10: 'f10',
        Qt.Key.Key_F11: 'f11',
        Qt.Key.Key_F12: 'f12',
        # Lock keys
        Qt.Key.Key_Pause: 'pause',
        Qt.Key.Key_ScrollLock: 'scroll_lock',
        Qt.Key.Key_NumLock: 'num_lock',
        Qt.Key.Key_CapsLock: 'caps_lock',
        # Punctuation/symbols
        Qt.Key.Key_Minus: 'minus',
        Qt.Key.Key_Plus: 'plus',
        Qt.Key.Key_Equal: 'equals',
        Qt.Key.Key_BracketLeft: 'bracket_left',
        Qt.Key.Key_BracketRight: 'bracket_right',
        Qt.Key.Key_Backslash: 'backslash',
        Qt.Key.Key_Semicolon: 'semicolon',
        Qt.Key.Key_Apostrophe: 'apostrophe',
        Qt.Key.Key_Comma: 'comma',
        Qt.Key.Key_Period: 'period',
        Qt.Key.Key_Slash: 'slash',
        Qt.Key.Key_QuoteLeft: 'grave',
        Qt.Key.Key_Asterisk: 'asterisk',
        # Numpad keys
        Qt.Key.Key_multiply: 'num_multiply',
        Qt.Key.Key_division: 'num_divide',
    }

    # Display names for internal key names
    KEY_DISPLAY_MAP = {
        'print_screen': 'Print Screen',
        'enter': 'Enter',
        'num_enter': 'Num Enter',
        'space': 'Space',
        'escape': 'Escape',
        'tab': 'Tab',
        'backspace': 'Backspace',
        'delete': 'Delete',
        'insert': 'Insert',
        'home': 'Home',
        'end': 'End',
        'page_up': 'Page Up',
        'page_down': 'Page Down',
        'up': 'Up',
        'down': 'Down',
        'left': 'Left',
        'right': 'Right',
        'pause': 'Pause',
        'scroll_lock': 'Scroll Lock',
        'num_lock': 'Num Lock',
        'caps_lock': 'Caps Lock',
        'minus': '-',
        'plus': '+',
        'equals': '=',
        'bracket_left': '[',
        'bracket_right': ']',
        'backslash': '\\',
        'semicolon': ';',
        'apostrophe': "'",
        'comma': ',',
        'period': '.',
        'slash': '/',
        'grave': '`',
        'asterisk': '*',
        'num_multiply': 'Num *',
        'num_divide': 'Num /',
        'num_minus': 'Num -',
        'num_plus': 'Num +',
        'num_decimal': 'Num .',
        'num_enter': 'Num Enter',
        'num_asterisk': 'Num *',
        'num_slash': 'Num /',
        'num_period': 'Num .',
    }

    def __init__(self, parent=None):
        super().__init__(parent)

        # Current hotkey state
        self._modifiers: List[str] = []
        self._key: str = ''
        self._recording = False

        # Setup UI
        self.setReadOnly(True)
        self.setPlaceholderText("Click and press keys...")
        self.setMinimumWidth(180)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._update_style()

    def _update_style(self):
        """Update widget style based on recording state."""
        if self._recording:
            self.setStyleSheet("""
                QLineEdit {
                    background-color: #3d3d3d;
                    border: 2px solid #4CAF50;
                    padding: 4px 8px;
                }
            """)
        else:
            self.setStyleSheet("""
                QLineEdit {
                    background-color: #2d2d2d;
                    border: 1px solid #3d3d3d;
                    padding: 4px 8px;
                }
                QLineEdit:hover {
                    border: 1px solid #4d4d4d;
                }
            """)

    def set_hotkey(self, modifiers: List[str], key: str):
        """
        Set the current hotkey from external values.

        Args:
            modifiers: List of modifier names (e.g., ['shift', 'ctrl'])
            key: Key name (e.g., 'print_screen', 'f5')
        """
        self._modifiers = [m.lower() for m in modifiers] if modifiers else []
        self._key = key.lower() if key else ''
        self._update_display()

    def get_hotkey(self) -> Tuple[List[str], str]:
        """
        Get the current hotkey as (modifiers, key).

        Returns:
            Tuple of (modifiers_list, key_name)
        """
        return (self._modifiers.copy(), self._key)

    def _update_display(self):
        """Update the displayed text to show current hotkey."""
        if not self._key and not self._modifiers:
            self.setText("")
            return

        parts = []

        # Add modifiers in consistent order
        if 'ctrl' in self._modifiers:
            parts.append('Ctrl')
        if 'shift' in self._modifiers:
            parts.append('Shift')
        if 'alt' in self._modifiers:
            parts.append('Alt')
        if 'win' in self._modifiers:
            parts.append('Win')

        # Add key
        if self._key:
            # Convert internal name to display name
            display_key = self._internal_to_display(self._key)
            parts.append(display_key)

        self.setText(' + '.join(parts))

    def _internal_to_display(self, internal_name: str) -> str:
        """Convert internal key name to display name."""
        # Check direct mapping
        if internal_name in self.KEY_DISPLAY_MAP:
            return self.KEY_DISPLAY_MAP[internal_name]

        # F keys
        if internal_name.lower().startswith('f') and internal_name[1:].isdigit():
            return internal_name.upper()

        # Numpad numbers (num_0, num_1, etc.)
        if internal_name.startswith('num_') and internal_name[4:].isdigit():
            return f"Num {internal_name[4:]}"

        # Single characters (letters, numbers)
        if len(internal_name) == 1:
            return internal_name.upper()

        return internal_name.replace('_', ' ').title()

    def focusInEvent(self, event: QFocusEvent):
        """Start recording when focused."""
        super().focusInEvent(event)
        self._recording = True
        self._update_style()
        self.setPlaceholderText("Press key combination...")

    def focusOutEvent(self, event: QFocusEvent):
        """Stop recording when focus lost."""
        super().focusOutEvent(event)
        self._recording = False
        self._update_style()
        self.setPlaceholderText("Click and press keys...")

    def keyPressEvent(self, event: QKeyEvent):
        """Handle key press to record hotkey."""
        if not self._recording:
            return

        key = event.key()
        modifiers = event.modifiers()

        # Ignore if only modifier keys pressed
        if key in self.MODIFIER_KEYS:
            return

        # Ignore Escape - use it to cancel/clear focus
        if key == Qt.Key.Key_Escape:
            self.clearFocus()
            return

        # Build modifier list (exclude KeypadModifier - it's not a user modifier)
        new_modifiers = []
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            new_modifiers.append('ctrl')
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            new_modifiers.append('shift')
        if modifiers & Qt.KeyboardModifier.AltModifier:
            new_modifiers.append('alt')
        if modifiers & Qt.KeyboardModifier.MetaModifier:
            new_modifiers.append('win')

        # Check if this is a numpad key
        is_numpad = bool(modifiers & Qt.KeyboardModifier.KeypadModifier)

        # Get key name
        new_key = self._get_key_name(key, is_numpad, event.text())

        if new_key:
            self._modifiers = new_modifiers
            self._key = new_key
            self._update_display()
            self.hotkey_changed.emit(self._modifiers, self._key)

            # Clear focus after recording
            self.clearFocus()

    def _get_key_name(self, key: int, is_numpad: bool = False, text: str = '') -> str:
        """Get internal key name from Qt key code."""
        # Check mapping first
        if key in self.KEY_INTERNAL_NAMES:
            base_name = self.KEY_INTERNAL_NAMES[key]
            # For keys that can be on numpad, prefix with num_
            if is_numpad and base_name in ('minus', 'plus', 'asterisk', 'slash', 'period', 'enter'):
                return f'num_{base_name}'
            return base_name

        # Letter keys (A-Z)
        if Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
            return chr(key).lower()

        # Number keys (0-9) - check numpad
        if Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
            if is_numpad:
                return f'num_{chr(key)}'
            return chr(key)

        # Fallback: use event text for printable characters
        if text and len(text) == 1 and text.isprintable():
            char = text.lower()
            if is_numpad:
                # Map numpad operators
                numpad_map = {'-': 'num_minus', '+': 'num_plus', '*': 'num_multiply',
                              '/': 'num_divide', '.': 'num_decimal'}
                if char in numpad_map:
                    return numpad_map[char]
                if char.isdigit():
                    return f'num_{char}'
            return char

        return ''

    def mousePressEvent(self, event):
        """Handle mouse click to gain focus."""
        super().mousePressEvent(event)
        self.setFocus()
