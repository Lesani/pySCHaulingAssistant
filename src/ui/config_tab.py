"""
Configuration tab for PyQt6.

Settings for API provider, model selection, and application preferences.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLineEdit, QComboBox, QSpinBox, QCheckBox, QPushButton,
    QLabel, QMessageBox, QScrollArea, QFrame
)
from PyQt6.QtCore import pyqtSignal, Qt
import os
from typing import Optional, TYPE_CHECKING

from src.config import Config
from src.sound_service import get_sound_service
from src.logger import get_logger

if TYPE_CHECKING:
    from src.discord_auth import DiscordAuth

logger = get_logger()


class ConfigTab(QWidget):
    """Configuration settings tab."""

    config_saved = pyqtSignal()  # Emitted when config is saved
    discord_login_requested = pyqtSignal()  # Emitted when user wants to login
    discord_logout_requested = pyqtSignal()  # Emitted when user wants to logout

    def __init__(self, config: Config, discord_auth: Optional["DiscordAuth"] = None):
        super().__init__()

        self.config = config
        self.discord_auth = discord_auth

        self._setup_ui()
        self._load_settings()
        self._update_discord_status()

    def _setup_ui(self):
        """Setup the configuration UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Create scroll area for all settings
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # Content widget inside scroll area
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 8, 0)  # Right margin for scrollbar
        content_layout.setSpacing(8)

        # API Settings Group
        api_group = QGroupBox("API Settings")
        api_layout = QFormLayout()

        # Provider selection
        self.provider_combo = QComboBox()
        self.provider_combo.addItems(["Anthropic", "OpenRouter"])
        self.provider_combo.currentTextChanged.connect(self._on_provider_changed)
        api_layout.addRow("Provider:", self.provider_combo)

        # API Key
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("Enter API key")
        self.api_key_edit.setMinimumWidth(250)

        # Show/hide button
        api_key_layout = QHBoxLayout()
        api_key_layout.addWidget(self.api_key_edit)

        self.show_key_btn = QPushButton("Show")
        self.show_key_btn.setMaximumWidth(60)
        self.show_key_btn.setProperty("class", "secondary")
        self.show_key_btn.clicked.connect(self._toggle_key_visibility)
        api_key_layout.addWidget(self.show_key_btn)

        # Set stretch so line edit expands, button stays fixed
        api_key_layout.setStretch(0, 1)
        api_key_layout.setStretch(1, 0)

        api_layout.addRow("API Key:", api_key_layout)

        # Environment variable hint
        self.env_var_label = QLabel()
        self.env_var_label.setProperty("class", "muted")
        self.env_var_label.setWordWrap(True)
        api_layout.addRow("", self.env_var_label)

        # Model selection
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.setMinimumWidth(200)
        api_layout.addRow("Model:", self.model_combo)

        # Max tokens
        self.max_tokens_spin = QSpinBox()
        self.max_tokens_spin.setRange(100, 16000)
        self.max_tokens_spin.setValue(1024)
        api_layout.addRow("Max Tokens:", self.max_tokens_spin)

        api_group.setLayout(api_layout)
        content_layout.addWidget(api_group)

        # UI Settings Group
        ui_group = QGroupBox("UI Settings")
        ui_layout = QFormLayout()

        # Auto-switch to hauling tab
        self.auto_switch_check = QCheckBox("Automatically switch to Hauling tab after saving mission")
        self.auto_switch_check.setChecked(True)
        ui_layout.addRow(self.auto_switch_check)

        # Canvas height
        self.canvas_height_spin = QSpinBox()
        self.canvas_height_spin.setRange(200, 800)
        self.canvas_height_spin.setValue(400)
        ui_layout.addRow("Preview Height:", self.canvas_height_spin)

        ui_group.setLayout(ui_layout)
        content_layout.addWidget(ui_group)

        # Capture Settings Group
        capture_group = QGroupBox("Image Capture Settings")
        capture_layout = QFormLayout()

        # Default brightness range
        self.brightness_spin = QSpinBox()
        self.brightness_spin.setRange(-100, 100)
        self.brightness_spin.setValue(0)
        capture_layout.addRow("Default Brightness:", self.brightness_spin)

        # Default contrast range
        self.contrast_spin = QSpinBox()
        self.contrast_spin.setRange(-100, 100)
        self.contrast_spin.setValue(0)
        capture_layout.addRow("Default Contrast:", self.contrast_spin)

        # Default gamma
        self.gamma_spin = QSpinBox()
        self.gamma_spin.setRange(50, 200)
        self.gamma_spin.setValue(100)
        capture_layout.addRow("Default Gamma (×100):", self.gamma_spin)

        capture_group.setLayout(capture_layout)
        content_layout.addWidget(capture_group)

        # Route Planner Settings Group
        route_group = QGroupBox("Route Planner Settings")
        route_layout = QFormLayout()

        # Ship selection
        self.ship_combo = QComboBox()
        self.ship_combo.setMinimumWidth(200)

        # Load ship profiles if available
        try:
            from src.ship_profiles import ShipManager
            self.ship_manager = ShipManager()
            ship_names = list(self.ship_manager.profiles.keys())
            self.ship_combo.addItems(ship_names)
            self.has_ship_profiles = True
        except ImportError:
            self.ship_manager = None
            self.ship_combo.addItem("Default (96 SCU)")
            self.has_ship_profiles = False

        # Capacity display label
        self.ship_capacity_label = QLabel()
        self.ship_capacity_label.setProperty("class", "muted")

        ship_layout = QHBoxLayout()
        ship_layout.addWidget(self.ship_combo)
        ship_layout.addWidget(self.ship_capacity_label)
        ship_layout.addStretch()

        self.ship_combo.currentTextChanged.connect(self._on_ship_changed)
        route_layout.addRow("Ship:", ship_layout)

        # Route quality preset (combines algorithm + optimization level)
        self.route_quality_combo = QComboBox()
        self.route_quality_combo.addItems(["Fast", "Balanced", "Best"])
        self.route_quality_combo.setMinimumWidth(150)
        self.route_quality_combo.setToolTip(
            "Fast: Quick results (~200ms)\n"
            "Balanced: Good quality (~500ms)\n"
            "Best: Maximum optimization (~3s)"
        )
        route_layout.addRow("Route Quality:", self.route_quality_combo)

        # Thread count for route finder parallel processing
        self.thread_count_spin = QSpinBox()
        self.thread_count_spin.setRange(1, 16)
        self.thread_count_spin.setValue(8)
        self.thread_count_spin.setToolTip(
            "Number of parallel processes for route optimization.\n"
            "Higher values use more CPU but can speed up searches."
        )
        route_layout.addRow("Route Finder Threads:", self.thread_count_spin)

        # Worker timeout for route finder
        self.worker_timeout_spin = QSpinBox()
        self.worker_timeout_spin.setRange(5, 120)
        self.worker_timeout_spin.setValue(30)
        self.worker_timeout_spin.setSuffix(" sec")
        self.worker_timeout_spin.setToolTip(
            "Timeout per worker task in seconds.\n"
            "Increase if route finding times out on complex searches."
        )
        route_layout.addRow("Worker Timeout:", self.worker_timeout_spin)

        route_group.setLayout(route_layout)
        content_layout.addWidget(route_group)

        # Global Hotkeys Group
        hotkeys_group = QGroupBox("Global Hotkeys (System-wide)")
        hotkeys_layout = QFormLayout()

        # Enable hotkeys checkbox
        self.hotkeys_enabled_check = QCheckBox("Enable global hotkeys")
        self.hotkeys_enabled_check.setChecked(True)
        hotkeys_layout.addRow(self.hotkeys_enabled_check)

        # Enable sounds checkbox
        self.sounds_enabled_check = QCheckBox("Enable sound notifications")
        self.sounds_enabled_check.setChecked(True)
        self.sounds_enabled_check.stateChanged.connect(self._on_sounds_toggled)
        hotkeys_layout.addRow(self.sounds_enabled_check)

        # Info label
        info_label = QLabel("These shortcuts work even when the game window is focused.")
        info_label.setProperty("class", "muted")
        info_label.setWordWrap(True)
        hotkeys_layout.addRow(info_label)

        # Capture hotkey
        capture_hotkey_layout = QHBoxLayout()
        self.capture_modifier_combo = QComboBox()
        self.capture_modifier_combo.addItems(["Shift", "Ctrl", "Alt", "Shift+Ctrl", "Shift+Alt", "Ctrl+Alt"])
        self.capture_modifier_combo.setMinimumWidth(100)
        capture_hotkey_layout.addWidget(self.capture_modifier_combo)
        capture_hotkey_layout.addWidget(QLabel("+"))
        self.capture_key_combo = QComboBox()
        self.capture_key_combo.addItems([
            "Print Screen", "Enter", "Space", "F1", "F2", "F3", "F4",
            "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12"
        ])
        self.capture_key_combo.setMinimumWidth(120)
        capture_hotkey_layout.addWidget(self.capture_key_combo)
        capture_hotkey_layout.addStretch()
        hotkeys_layout.addRow("Capture & Extract:", capture_hotkey_layout)

        # Save hotkey
        save_hotkey_layout = QHBoxLayout()
        self.save_modifier_combo = QComboBox()
        self.save_modifier_combo.addItems(["Shift", "Ctrl", "Alt", "Shift+Ctrl", "Shift+Alt", "Ctrl+Alt"])
        self.save_modifier_combo.setMinimumWidth(100)
        save_hotkey_layout.addWidget(self.save_modifier_combo)
        save_hotkey_layout.addWidget(QLabel("+"))
        self.save_key_combo = QComboBox()
        self.save_key_combo.addItems([
            "Enter", "Space", "Print Screen", "F1", "F2", "F3", "F4",
            "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12"
        ])
        self.save_key_combo.setMinimumWidth(120)
        save_hotkey_layout.addWidget(self.save_key_combo)
        save_hotkey_layout.addStretch()
        hotkeys_layout.addRow("Add to List:", save_hotkey_layout)

        hotkeys_group.setLayout(hotkeys_layout)
        content_layout.addWidget(hotkeys_group)

        # Cloud Sync Settings Group
        sync_group = QGroupBox("Cloud Sync Settings")
        sync_layout = QFormLayout()

        # Info label
        sync_info_label = QLabel(
            "Sync your scanned missions with an online database to share with friends.\n"
            "Login with Discord to authenticate and sync."
        )
        sync_info_label.setProperty("class", "muted")
        sync_info_label.setWordWrap(True)
        sync_layout.addRow(sync_info_label)

        # API URL
        self.sync_url_edit = QLineEdit()
        self.sync_url_edit.setPlaceholderText("https://your-worker.workers.dev")
        self.sync_url_edit.setMinimumWidth(300)
        sync_layout.addRow("Sync API URL:", self.sync_url_edit)

        # Discord Authentication section
        auth_layout = QHBoxLayout()

        # Status label (shows logged in username or "Not logged in")
        self.discord_status_label = QLabel("Not logged in")
        self.discord_status_label.setMinimumWidth(150)
        auth_layout.addWidget(self.discord_status_label)

        # Login button
        self.discord_login_btn = QPushButton("Login with Discord")
        self.discord_login_btn.clicked.connect(self._on_discord_login_clicked)
        auth_layout.addWidget(self.discord_login_btn)

        # Logout button (hidden when not logged in)
        self.discord_logout_btn = QPushButton("Logout")
        self.discord_logout_btn.setProperty("class", "secondary")
        self.discord_logout_btn.clicked.connect(self._on_discord_logout_clicked)
        self.discord_logout_btn.hide()
        auth_layout.addWidget(self.discord_logout_btn)

        auth_layout.addStretch()
        sync_layout.addRow("Authentication:", auth_layout)

        # Test connection button
        test_btn_layout = QHBoxLayout()
        self.test_sync_btn = QPushButton("Test Connection")
        self.test_sync_btn.setProperty("class", "secondary")
        self.test_sync_btn.clicked.connect(self._test_sync_connection)
        test_btn_layout.addWidget(self.test_sync_btn)
        test_btn_layout.addStretch()
        sync_layout.addRow("", test_btn_layout)

        sync_group.setLayout(sync_layout)
        content_layout.addWidget(sync_group)

        content_layout.addStretch()

        # Finalize scroll area
        scroll.setWidget(content_widget)
        layout.addWidget(scroll, 1)  # stretch=1 so scroll takes available space

        # Action buttons (outside scroll area, always visible at bottom)
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.setProperty("class", "secondary")
        reset_btn.clicked.connect(self._reset_to_defaults)
        button_layout.addWidget(reset_btn)

        save_btn = QPushButton("Save Configuration")
        save_btn.clicked.connect(self._save_config)
        button_layout.addWidget(save_btn)

        layout.addLayout(button_layout)

    def _load_settings(self):
        """Load current settings into the form."""
        # API settings
        provider = self.config.get("api", "provider", default="anthropic")
        # Find and select provider (case-insensitive)
        for i in range(self.provider_combo.count()):
            if self.provider_combo.itemText(i).lower() == provider.lower():
                self.provider_combo.setCurrentIndex(i)
                break

        # Load API key from config or environment
        api_key = self.config.get_api_key()
        if api_key:
            self.api_key_edit.setText(api_key)

        # Model - load from provider-specific config
        model = self.config.get("api", provider, "default_model", default="claude-sonnet-4-5")
        self.model_combo.setCurrentText(model)

        # Max tokens
        max_tokens = self.config.get("api", "max_tokens", default=1024)
        self.max_tokens_spin.setValue(max_tokens)

        # UI settings
        auto_switch = self.config.get("ui", "auto_switch_to_hauling", default=True)
        self.auto_switch_check.setChecked(auto_switch)

        canvas_height = self.config.get("ui", "canvas_height", default=400)
        self.canvas_height_spin.setValue(canvas_height)

        # Capture settings
        brightness = self.config.get("capture", "default_brightness", default=0)
        self.brightness_spin.setValue(brightness)

        contrast = self.config.get("capture", "default_contrast", default=0)
        self.contrast_spin.setValue(contrast)

        gamma = self.config.get("capture", "default_gamma", default=100)
        self.gamma_spin.setValue(gamma)

        # Hotkey settings
        hotkeys_enabled = self.config.get("hotkeys", "enabled", default=True)
        self.hotkeys_enabled_check.setChecked(hotkeys_enabled)

        # Sound settings
        sounds_enabled = self.config.get("sounds", "enabled", default=True)
        self.sounds_enabled_check.setChecked(sounds_enabled)

        # Capture hotkey
        capture_modifiers = self.config.get("hotkeys", "capture", "modifiers", default=["shift"])
        capture_key = self.config.get("hotkeys", "capture", "key", default="print_screen")
        self._set_hotkey_combo(self.capture_modifier_combo, capture_modifiers)
        self._set_key_combo(self.capture_key_combo, capture_key)

        # Save hotkey
        save_modifiers = self.config.get("hotkeys", "save", "modifiers", default=["shift"])
        save_key = self.config.get("hotkeys", "save", "key", default="enter")
        self._set_hotkey_combo(self.save_modifier_combo, save_modifiers)
        self._set_key_combo(self.save_key_combo, save_key)

        # Update model list based on provider (use display text from combo)
        self._on_provider_changed(self.provider_combo.currentText())

        # Sync settings
        sync_url = self.config.get("sync", "api_url", default="")
        self.sync_url_edit.setText(sync_url)

        # Route planner settings
        saved_ship = self.config.get("route_planner", "selected_ship", default="ARGO_RAFT")
        if self.has_ship_profiles and saved_ship in [self.ship_combo.itemText(i) for i in range(self.ship_combo.count())]:
            self.ship_combo.setCurrentText(saved_ship)
        self._update_ship_capacity()

        route_quality = self.config.get("route_planner", "route_quality", default="best")
        self.route_quality_combo.setCurrentText(route_quality.capitalize())

        # Route finder parallel settings
        thread_count = self.config.get("route_finder", "thread_count", default=8)
        self.thread_count_spin.setValue(thread_count)

        worker_timeout = self.config.get("route_finder", "worker_timeout", default=30)
        self.worker_timeout_spin.setValue(worker_timeout)

        logger.debug("Configuration loaded")

    def _set_hotkey_combo(self, combo: QComboBox, modifiers: list):
        """Set the modifier combo box based on a list of modifiers."""
        # Convert list to display string
        if not modifiers:
            combo.setCurrentText("Shift")
            return

        # Sort for consistent display
        sorted_mods = sorted([m.capitalize() for m in modifiers])
        display_text = "+".join(sorted_mods)

        # Try to find exact match
        for i in range(combo.count()):
            if combo.itemText(i) == display_text:
                combo.setCurrentIndex(i)
                return

        # Default to first item
        combo.setCurrentIndex(0)

    def _set_key_combo(self, combo: QComboBox, key: str):
        """Set the key combo box based on a key string."""
        # Convert internal key name to display name
        key_map = {
            "print_screen": "Print Screen",
            "enter": "Enter",
            "space": "Space",
            "f1": "F1", "f2": "F2", "f3": "F3", "f4": "F4",
            "f5": "F5", "f6": "F6", "f7": "F7", "f8": "F8",
            "f9": "F9", "f10": "F10", "f11": "F11", "f12": "F12"
        }

        display_key = key_map.get(key.lower(), key.capitalize())

        # Try to find match
        for i in range(combo.count()):
            if combo.itemText(i) == display_key:
                combo.setCurrentIndex(i)
                return

        # Default to first item
        combo.setCurrentIndex(0)

    def _get_modifiers_list(self, display_text: str) -> list:
        """Convert display text to list of modifier keys."""
        # Split by + and convert to lowercase
        return [mod.strip().lower() for mod in display_text.split("+")]

    def _get_key_value(self, display_text: str) -> str:
        """Convert display text to internal key value."""
        # Convert display name to internal key name
        key_map = {
            "Print Screen": "print_screen",
            "Enter": "enter",
            "Space": "space",
            "F1": "f1", "F2": "f2", "F3": "f3", "F4": "f4",
            "F5": "f5", "F6": "f6", "F7": "f7", "F8": "f8",
            "F9": "f9", "F10": "f10", "F11": "f11", "F12": "f12"
        }

        return key_map.get(display_text, display_text.lower())

    def _on_ship_changed(self, ship_name: str):
        """Handle ship selection change."""
        self._update_ship_capacity()

    def _update_ship_capacity(self):
        """Update the capacity label based on selected ship."""
        ship_name = self.ship_combo.currentText()
        if self.has_ship_profiles and self.ship_manager and ship_name in self.ship_manager.profiles:
            capacity = self.ship_manager.profiles[ship_name].cargo_capacity_scu
            self.ship_capacity_label.setText(f"{capacity} SCU")
        else:
            self.ship_capacity_label.setText("96 SCU")

    def _on_provider_changed(self, provider: str):
        """Handle provider selection change."""
        provider_lower = provider.lower()

        # Update model list
        self.model_combo.clear()
        if provider_lower == "anthropic":
            self.model_combo.addItems([
                "claude-sonnet-4-5",
                "claude-3-5-sonnet-20241022",
                "claude-3-5-sonnet-20240620",
                "claude-3-opus-20240229",
                "claude-3-haiku-20240307"
            ])
            self.env_var_label.setText(
                "Key saved to config.json. Can also use ANTHROPIC_API_KEY env var."
            )

            # Load saved model for this provider
            saved_model = self.config.get("api", "anthropic", "default_model", default="claude-sonnet-4-5")
            self.model_combo.setCurrentText(saved_model)
        else:  # openrouter
            self.model_combo.addItems([
                "qwen/qwen3-vl-8b-instruct",
                "anthropic/claude-3.5-sonnet",
                "anthropic/claude-3-opus",
                "openai/gpt-4-turbo",
                "google/gemini-pro-1.5"
            ])
            self.env_var_label.setText(
                "Key saved to config.json. Can also use OPENROUTER_API_KEY env var."
            )

            # Load saved model for this provider
            saved_model = self.config.get("api", "openrouter", "default_model", default="qwen/qwen3-vl-8b-instruct")
            self.model_combo.setCurrentText(saved_model)

    def _toggle_key_visibility(self):
        """Toggle API key visibility."""
        if self.api_key_edit.echoMode() == QLineEdit.EchoMode.Password:
            self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Normal)
            self.show_key_btn.setText("Hide")
        else:
            self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self.show_key_btn.setText("Show")

    def _on_sounds_toggled(self, state: int):
        """Handle sounds checkbox toggle - update immediately."""
        enabled = state == Qt.CheckState.Checked.value
        get_sound_service().enabled = enabled

    def _save_config(self):
        """Save configuration to file."""
        try:
            # Update config
            provider = self.provider_combo.currentText().lower()

            if "api" not in self.config.settings:
                self.config.settings["api"] = {}

            self.config.settings["api"]["provider"] = provider

            # Save model to provider-specific config
            if provider not in self.config.settings["api"]:
                self.config.settings["api"][provider] = {}

            self.config.settings["api"][provider]["default_model"] = self.model_combo.currentText()
            self.config.settings["api"]["max_tokens"] = self.max_tokens_spin.value()

            # Save API key to config file
            api_key = self.api_key_edit.text().strip()
            if api_key:
                self.config.settings["api"]["api_key"] = api_key
            else:
                # Clear stored key if field is empty
                self.config.settings["api"].pop("api_key", None)

            # UI settings
            if "ui" not in self.config.settings:
                self.config.settings["ui"] = {}

            auto_switch_value = self.auto_switch_check.isChecked()
            self.config.settings["ui"]["auto_switch_to_hauling"] = auto_switch_value
            self.config.settings["ui"]["canvas_height"] = self.canvas_height_spin.value()
            logger.debug(f"Saving auto_switch_to_hauling: {auto_switch_value}")

            # Capture settings
            if "capture" not in self.config.settings:
                self.config.settings["capture"] = {}

            self.config.settings["capture"]["default_brightness"] = self.brightness_spin.value()
            self.config.settings["capture"]["default_contrast"] = self.contrast_spin.value()
            self.config.settings["capture"]["default_gamma"] = self.gamma_spin.value()

            # Hotkey settings
            if "hotkeys" not in self.config.settings:
                self.config.settings["hotkeys"] = {}

            self.config.settings["hotkeys"]["enabled"] = self.hotkeys_enabled_check.isChecked()

            # Capture hotkey
            capture_modifiers = self._get_modifiers_list(self.capture_modifier_combo.currentText())
            capture_key = self._get_key_value(self.capture_key_combo.currentText())

            if "capture" not in self.config.settings["hotkeys"]:
                self.config.settings["hotkeys"]["capture"] = {}

            self.config.settings["hotkeys"]["capture"]["modifiers"] = capture_modifiers
            self.config.settings["hotkeys"]["capture"]["key"] = capture_key
            self.config.settings["hotkeys"]["capture"]["description"] = "Capture & extract mission from screen"

            # Save hotkey
            save_modifiers = self._get_modifiers_list(self.save_modifier_combo.currentText())
            save_key = self._get_key_value(self.save_key_combo.currentText())

            if "save" not in self.config.settings["hotkeys"]:
                self.config.settings["hotkeys"]["save"] = {}

            self.config.settings["hotkeys"]["save"]["modifiers"] = save_modifiers
            self.config.settings["hotkeys"]["save"]["key"] = save_key
            self.config.settings["hotkeys"]["save"]["description"] = "Add mission to hauling list"

            # Sound settings
            if "sounds" not in self.config.settings:
                self.config.settings["sounds"] = {}

            self.config.settings["sounds"]["enabled"] = self.sounds_enabled_check.isChecked()

            # Sync settings
            if "sync" not in self.config.settings:
                self.config.settings["sync"] = {}

            self.config.settings["sync"]["api_url"] = self.sync_url_edit.text().strip()

            # Route planner settings
            if "route_planner" not in self.config.settings:
                self.config.settings["route_planner"] = {}

            ship_name = self.ship_combo.currentText()
            self.config.settings["route_planner"]["selected_ship"] = ship_name

            # Save ship capacity
            if self.has_ship_profiles and self.ship_manager and ship_name in self.ship_manager.profiles:
                capacity = self.ship_manager.profiles[ship_name].cargo_capacity_scu
            else:
                capacity = 96
            self.config.settings["route_planner"]["ship_capacity"] = capacity

            self.config.settings["route_planner"]["route_quality"] = self.route_quality_combo.currentText().lower()

            # Route finder parallel settings
            if "route_finder" not in self.config.settings:
                self.config.settings["route_finder"] = {}

            self.config.settings["route_finder"]["thread_count"] = self.thread_count_spin.value()
            self.config.settings["route_finder"]["worker_timeout"] = self.worker_timeout_spin.value()

            # Save to file
            self.config.save()

            # Emit signal
            self.config_saved.emit()

            QMessageBox.information(self, "Success", "Configuration saved successfully")
            logger.info("Configuration saved")

        except Exception as e:
            logger.error(f"Failed to save config: {e}")
            QMessageBox.critical(self, "Error", f"Failed to save configuration:\n{str(e)}")

    def _reset_to_defaults(self):
        """Reset all settings to defaults."""
        reply = QMessageBox.question(
            self,
            "Reset to Defaults",
            "Are you sure you want to reset all settings to defaults?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            # Reset API settings
            self.provider_combo.setCurrentText("Anthropic")
            self.api_key_edit.clear()
            self.model_combo.setCurrentText("claude-sonnet-4-5")
            self.max_tokens_spin.setValue(1024)

            # Reset UI settings
            self.auto_switch_check.setChecked(True)
            self.canvas_height_spin.setValue(400)

            # Reset capture settings
            self.brightness_spin.setValue(0)
            self.contrast_spin.setValue(0)
            self.gamma_spin.setValue(100)

            # Reset hotkey settings
            self.hotkeys_enabled_check.setChecked(True)
            self.capture_modifier_combo.setCurrentText("Shift")
            self.capture_key_combo.setCurrentText("Print Screen")
            self.save_modifier_combo.setCurrentText("Shift")
            self.save_key_combo.setCurrentText("Enter")

            # Reset sound settings
            self.sounds_enabled_check.setChecked(True)

            # Reset sync settings
            self.sync_url_edit.setText("")

            # Reset route finder parallel settings
            self.thread_count_spin.setValue(8)
            self.worker_timeout_spin.setValue(30)

            logger.info("Settings reset to defaults")

    def _test_sync_connection(self):
        """Test connection to the sync API."""
        from src.sync_service import SyncService

        url = self.sync_url_edit.text().strip()
        if not url:
            QMessageBox.warning(
                self,
                "No URL",
                "Please enter a Sync API URL first."
            )
            return

        # Temporarily update config for testing
        if "sync" not in self.config.settings:
            self.config.settings["sync"] = {}
        self.config.settings["sync"]["api_url"] = url

        sync_service = SyncService(self.config)

        self.test_sync_btn.setEnabled(False)
        self.test_sync_btn.setText("Testing...")

        result = sync_service.test_connection()

        self.test_sync_btn.setEnabled(True)
        self.test_sync_btn.setText("Test Connection")

        if result.get("success"):
            # Also get stats
            stats_result = sync_service.get_stats()
            stats_msg = ""
            if stats_result.get("success"):
                stats = stats_result.get("stats", {})
                stats_msg = f"\n\nDatabase stats:\n"
                stats_msg += f"  Total scans: {stats.get('total_scans', 0)}\n"
                stats_msg += f"  Last 24h: {stats.get('scans_last_24h', 0)}"

            QMessageBox.information(
                self,
                "Connection Successful",
                f"Successfully connected to sync server!{stats_msg}"
            )
        else:
            QMessageBox.critical(
                self,
                "Connection Failed",
                f"Could not connect to sync server:\n\n{result.get('error', 'Unknown error')}"
            )

    def _update_discord_status(self):
        """Update the Discord login status display."""
        if self.discord_auth and self.discord_auth.is_logged_in():
            username = self.discord_auth.get_username() or "Unknown"
            self.discord_status_label.setText(f"Logged in as: {username}")
            self.discord_status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
            self.discord_login_btn.setVisible(False)
            self.discord_logout_btn.setVisible(True)
        else:
            self.discord_status_label.setText("Not logged in")
            self.discord_status_label.setStyleSheet("color: #888;")
            self.discord_login_btn.setVisible(True)
            self.discord_logout_btn.setVisible(False)

    def _on_discord_login_clicked(self):
        """Handle Discord login button click."""
        if not self.discord_auth:
            QMessageBox.warning(
                self,
                "Not Available",
                "Discord authentication is not initialized."
            )
            return

        self.discord_login_btn.setEnabled(False)
        self.discord_login_btn.setText("Logging in...")

        # Emit signal to let main window handle the actual login
        self.discord_login_requested.emit()

    def _on_discord_logout_clicked(self):
        """Handle Discord logout button click."""
        if not self.discord_auth:
            return

        reply = QMessageBox.question(
            self,
            "Logout",
            "Are you sure you want to logout from Discord?\n\n"
            "You will need to login again to sync missions.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.discord_logout_requested.emit()

    def on_discord_login_complete(self, success: bool, message: str):
        """Called when Discord login completes."""
        self.discord_login_btn.setEnabled(True)
        self.discord_login_btn.setText("Login with Discord")

        if success:
            self._update_discord_status()
        else:
            QMessageBox.warning(
                self,
                "Login Failed",
                f"Could not login with Discord:\n\n{message}"
            )

    def on_discord_logout_complete(self):
        """Called when Discord logout completes."""
        self._update_discord_status()

    def set_discord_auth(self, discord_auth: "DiscordAuth"):
        """Set the Discord auth instance and update status."""
        self.discord_auth = discord_auth
        self._update_discord_status()
