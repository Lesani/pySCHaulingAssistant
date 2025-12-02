"""
Main application window with PyQt6.

Modern tabbed interface with Capture, Hauling, Route Planner, and Configuration tabs.
"""

from PyQt6.QtWidgets import (
    QMainWindow, QTabWidget, QWidget, QVBoxLayout,
    QStatusBar, QMessageBox
)
from PyQt6.QtCore import Qt, QSettings, pyqtSignal, QTimer
from PyQt6.QtGui import QIcon, QCloseEvent

from src.config import Config
from src.api_client import APIClient
from src.mission_manager import MissionManager
from src.mission_scan_db import MissionScanDB
from src.location_autocomplete import LocationMatcher
from src.cargo_autocomplete import CargoMatcher
from src.global_hotkeys import GlobalHotkeyManager
from src.discord_auth import DiscordAuth
from src.logger import get_logger

# Import tabs (will be created)
from src.ui.capture_tab import CaptureTab
from src.ui.hauling_tab import HaulingTab
from src.ui.route_planner_tab import RoutePlannerTab
from src.ui.scan_database_tab import ScanDatabaseTab
from src.ui.screenshot_parser_tab import ScreenshotParserTab
from src.ui.config_tab import ConfigTab
from src.ui.styles import get_stylesheet

logger = get_logger()


class MainWindow(QMainWindow):
    """Main application window with modern PyQt6 interface."""

    # Signal for thread-safe login completion
    _login_complete_signal = pyqtSignal(bool, str)

    def __init__(self, config: Config):
        super().__init__()

        self.config = config
        self.api_client = APIClient(config)
        self.mission_manager = MissionManager()
        self.scan_db = MissionScanDB()
        self.location_matcher = LocationMatcher()
        self.cargo_matcher = CargoMatcher()

        # Discord authentication
        self.discord_auth = DiscordAuth(config)

        # Window settings
        self.settings = QSettings("SCHaulingAssistant", "MainWindow")

        # Global hotkey manager
        self.hotkey_manager = GlobalHotkeyManager()

        self._setup_ui()
        self._apply_theme()
        self._restore_geometry()
        self._setup_global_hotkeys()

        # Connect login complete signal
        self._login_complete_signal.connect(self._on_discord_login_complete)

        logger.info("Main window initialized")

    def _setup_ui(self):
        """Initialize the user interface."""
        self.setWindowTitle("SC Hauling Assistant")
        self.setMinimumSize(1000, 875)

        # Create central widget with tab widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Create tab widget
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabPosition(QTabWidget.TabPosition.North)
        self.tab_widget.setDocumentMode(True)
        layout.addWidget(self.tab_widget)

        # Create tabs
        self.capture_tab = CaptureTab(
            self.config,
            self.api_client,
            self.location_matcher,
            self.cargo_matcher,
            self.scan_db,
            self._on_mission_saved,
            self._get_active_missions
        )
        self.hauling_tab = HaulingTab(
            self.config,
            self.mission_manager,
            self.location_matcher,
            self.cargo_matcher
        )
        self.route_planner_tab = RoutePlannerTab(
            self.config,
            self.mission_manager
        )
        self.scan_database_tab = ScanDatabaseTab(self.scan_db, self.config, self.discord_auth)
        self.screenshot_parser_tab = ScreenshotParserTab(
            self.config,
            self.api_client,
            self.location_matcher,
            self.cargo_matcher,
            self.scan_db
        )
        self.config_tab = ConfigTab(self.config, self.discord_auth)

        # Connect scan added signals
        self.capture_tab.scan_added.connect(self.scan_database_tab.add_scan_to_table)
        self.screenshot_parser_tab.scan_added.connect(self.scan_database_tab.add_scan_to_table)

        # Connect status message signal from capture tab
        self.capture_tab.status_message.connect(self._on_capture_status_message)

        # Connect Discord auth signals
        self.config_tab.discord_login_requested.connect(self._on_discord_login_requested)
        self.config_tab.discord_logout_requested.connect(self._on_discord_logout_requested)
        self.scan_database_tab.login_requested.connect(self._on_discord_login_requested)

        # Add tabs
        self.tab_widget.addTab(self.capture_tab, "Capture")
        self.tab_widget.addTab(self.hauling_tab, "Hauling")
        self.tab_widget.addTab(self.route_planner_tab, "Route Planner")
        self.tab_widget.addTab(self.scan_database_tab, "Scan Database")
        self.tab_widget.addTab(self.screenshot_parser_tab, "Screenshot Parser")
        self.tab_widget.addTab(self.config_tab, "Configuration")

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

        # Connect signals
        self.tab_widget.currentChanged.connect(self._on_tab_changed)
        self.config_tab.config_saved.connect(self._on_config_saved)

        logger.debug("UI setup complete")

    def _apply_theme(self):
        """Apply the modern dark theme."""
        self.setStyleSheet(get_stylesheet())
        logger.debug("Dark theme applied")

    def _restore_geometry(self):
        """Restore window geometry from settings."""
        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        else:
            # Default size and center on screen
            self.resize(1000, 700)
            screen = self.screen().geometry()
            x = (screen.width() - self.width()) // 2
            y = (screen.height() - self.height()) // 2
            self.move(x, y)

    def _save_geometry(self):
        """Save window geometry to settings."""
        self.settings.setValue("geometry", self.saveGeometry())

    def _on_tab_changed(self, index: int):
        """Handle tab changes."""
        tab_name = self.tab_widget.tabText(index)
        logger.debug(f"Switched to tab: {tab_name}")

        # Refresh data when switching to certain tabs
        if index == 1:  # Hauling tab
            self.hauling_tab.refresh()
        elif index == 2:  # Route Planner tab
            self.route_planner_tab.refresh()

    def _get_active_missions(self):
        """Get list of active missions for synergy analysis."""
        from src.domain.models import MissionStatus, Mission, Objective

        # Get missions with "active" status (as string)
        mission_dicts = self.mission_manager.get_missions(status="active")

        # Convert dictionaries to Mission objects for synergy analysis
        missions = []
        for m_dict in mission_dicts:
            try:
                objectives = [
                    Objective(
                        collect_from=obj.get('collect_from', ''),
                        deliver_to=obj.get('deliver_to', ''),
                        scu_amount=obj.get('scu_amount', 0),
                        cargo_type=obj.get('cargo_type', 'Unknown'),
                        mission_id=obj.get('mission_id')
                    )
                    for obj in m_dict.get('objectives', [])
                ]

                mission = Mission(
                    id=m_dict.get('id', ''),
                    reward=float(m_dict.get('reward', 0)),
                    availability=m_dict.get('availability', '00:00:00'),
                    objectives=objectives,
                    timestamp=m_dict.get('timestamp', ''),
                    status=m_dict.get('status', 'active')
                )
                missions.append(mission)
            except Exception as e:
                logger.error(f"Error converting mission dict to Mission object: {e}")
                continue

        return missions

    def _on_mission_saved(self, mission_data: dict):
        """Handle mission saved from capture tab."""
        try:
            # Add mission
            self.mission_manager.add_mission(mission_data)

            # Refresh hauling tab
            self.hauling_tab.refresh()

            # Automatic replanning: refresh route planner tab
            # This triggers dynamic re-optimization with new mission
            self.route_planner_tab.refresh()
            logger.debug("Route automatically replanned with new mission")

            # Stay on capture tab (auto-switch disabled)
            auto_switch = self.config.get("ui", "auto_switch_to_hauling", default=False)
            logger.debug(f"Auto-switch setting: {auto_switch}")
            if auto_switch:
                self.tab_widget.setCurrentIndex(1)
                logger.debug("Switched to hauling tab")

            self.status_bar.showMessage("Mission added successfully - Route replanned", 3000)
            logger.info("Mission saved and added to hauling list")

        except Exception as e:
            logger.error(f"Failed to save mission: {e}")
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to save mission:\n{str(e)}"
            )

    def _on_config_saved(self):
        """Handle configuration saved."""
        self.status_bar.showMessage("Configuration saved", 3000)

        # Reinitialize API client with new config
        self.api_client = APIClient(self.config)
        self.capture_tab.api_client = self.api_client
        self.screenshot_parser_tab.api_client = self.api_client

        # Reload route planner config (ship, algorithm, etc.)
        self.route_planner_tab.reload_config()

        # Reload global hotkeys
        self.hotkey_manager.stop()
        self._setup_global_hotkeys()

        logger.info("Configuration updated")

    def _on_capture_status_message(self, message: str, timeout_ms: int):
        """Handle status messages from the capture tab."""
        self.status_bar.showMessage(message, timeout_ms)

    def _on_discord_login_requested(self):
        """Handle Discord login request."""
        self.status_bar.showMessage("Opening Discord login...", 3000)

        import threading

        def do_login():
            try:
                result = self.discord_auth.start_login_flow()
                # Emit signal to update UI on main thread
                self._login_complete_signal.emit(
                    result.get("success", False),
                    result.get("message", result.get("error", "Unknown error"))
                )
            except Exception as e:
                logger.error(f"Error in login thread: {e}")
                self._login_complete_signal.emit(False, str(e))

        # Start login in background thread to not block UI
        login_thread = threading.Thread(target=do_login, daemon=True)
        login_thread.start()

    def _on_discord_login_complete(self, success: bool, message: str):
        """Handle Discord login completion."""
        self.config_tab.on_discord_login_complete(success, message)

        if success:
            self.status_bar.showMessage(f"Logged in as {self.discord_auth.get_username()}", 3000)
            logger.info(f"Discord login successful: {self.discord_auth.get_username()}")
        else:
            self.status_bar.showMessage("Login failed", 3000)
            logger.warning(f"Discord login failed: {message}")

    def _on_discord_logout_requested(self):
        """Handle Discord logout request."""
        self.discord_auth.logout()
        self.config_tab.on_discord_logout_complete()
        self.status_bar.showMessage("Logged out from Discord", 3000)
        logger.info("Discord logout completed")

    def _setup_global_hotkeys(self):
        """Setup global hotkeys from configuration."""
        hotkey_config = self.config.get("hotkeys", default={})

        if not hotkey_config.get("enabled", False):
            logger.info("Global hotkeys disabled in configuration")
            return

        # Capture hotkey
        capture_config = hotkey_config.get("capture", {})
        if capture_config:
            self.hotkey_manager.register(
                name="capture",
                modifiers=capture_config.get("modifiers", []),
                key=capture_config.get("key", ""),
                callback=self._hotkey_capture,
                description=capture_config.get("description", "Capture mission")
            )

        # Save hotkey
        save_config = hotkey_config.get("save", {})
        if save_config:
            self.hotkey_manager.register(
                name="save",
                modifiers=save_config.get("modifiers", []),
                key=save_config.get("key", ""),
                callback=self._hotkey_save,
                description=save_config.get("description", "Save mission")
            )

        # Start listening
        self.hotkey_manager.start()
        logger.info("Global hotkeys initialized")

    def _hotkey_capture(self):
        """Handle capture hotkey press."""
        logger.debug("Capture hotkey triggered")
        try:
            # Switch to capture tab if not already there
            self.tab_widget.setCurrentIndex(0)

            # Use QTimer.singleShot for thread-safe GUI updates from hotkey thread
            QTimer.singleShot(0, self.capture_tab._capture_and_extract)
        except Exception as e:
            logger.error(f"Error in capture hotkey: {e}")

    def _hotkey_save(self):
        """Handle save hotkey press."""
        logger.debug("Save hotkey triggered")
        try:
            # Use QTimer.singleShot for thread-safe GUI updates from hotkey thread
            QTimer.singleShot(0, self.capture_tab.validation_form._save_mission)
        except Exception as e:
            logger.error(f"Error in save hotkey: {e}")

    def closeEvent(self, event: QCloseEvent):
        """Handle window close event."""
        # Stop global hotkey listener
        if hasattr(self, 'hotkey_manager'):
            self.hotkey_manager.stop()

        self._save_geometry()
        logger.info("Application closing")
        event.accept()
