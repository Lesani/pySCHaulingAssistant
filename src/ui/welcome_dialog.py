"""
Welcome dialog shown on application startup.

Allows users to select their ship and choose whether to continue
their previous session or start fresh.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QRadioButton, QButtonGroup, QPushButton, QGroupBox,
    QFrame
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from src.config import Config
from src.ship_profiles import SHIP_PROFILES, ShipProfile
from src.logger import get_logger

logger = get_logger()


class WelcomeDialog(QDialog):
    """
    Welcome dialog for session setup.

    Allows selecting ship and choosing to continue or start fresh.
    """

    def __init__(self, config: Config, has_active_missions: bool, parent=None):
        super().__init__(parent)
        self.config = config
        self.has_active_missions = has_active_missions

        self.selected_ship_key: str = ""
        self.start_fresh: bool = False

        self._setup_ui()
        self._load_last_settings()

    def _setup_ui(self):
        """Initialize the dialog UI."""
        self.setWindowTitle("SC Hauling Assistant")
        self.setMinimumWidth(450)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(30, 30, 30, 30)

        # Title
        title = QLabel("Welcome, Hauler!")
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # Subtitle
        subtitle = QLabel("Configure your session before starting")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #888; margin-bottom: 10px;")
        layout.addWidget(subtitle)

        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet("background-color: #444;")
        layout.addWidget(separator)

        # Ship selection group
        ship_group = QGroupBox("Select Your Ship")
        ship_layout = QVBoxLayout(ship_group)

        self.ship_combo = QComboBox()
        self.ship_combo.setMinimumHeight(35)

        # Sort ships by capacity and add to combo
        ships_sorted = sorted(
            SHIP_PROFILES.items(),
            key=lambda x: x[1].cargo_capacity_scu
        )

        for ship_key, ship in ships_sorted:
            display_text = f"{ship.display_name} ({ship.cargo_capacity_scu} SCU)"
            self.ship_combo.addItem(display_text, ship_key)

        ship_layout.addWidget(self.ship_combo)

        # Ship info label
        self.ship_info_label = QLabel()
        self.ship_info_label.setStyleSheet("color: #888; font-size: 11px; padding: 5px;")
        self.ship_info_label.setWordWrap(True)
        ship_layout.addWidget(self.ship_info_label)

        self.ship_combo.currentIndexChanged.connect(self._on_ship_changed)

        layout.addWidget(ship_group)

        # Session choice group
        session_group = QGroupBox("Session")
        session_layout = QVBoxLayout(session_group)

        self.session_button_group = QButtonGroup(self)

        # Continue option
        self.continue_radio = QRadioButton("Continue previous session")
        self.continue_radio.setChecked(True)
        self.session_button_group.addButton(self.continue_radio, 0)
        session_layout.addWidget(self.continue_radio)

        # Continue description
        if self.has_active_missions:
            continue_desc = QLabel("Resume with your existing missions and route")
        else:
            continue_desc = QLabel("No active missions found")
        continue_desc.setStyleSheet("color: #888; font-size: 11px; margin-left: 25px; margin-bottom: 10px;")
        session_layout.addWidget(continue_desc)

        # Fresh start option
        self.fresh_radio = QRadioButton("Start fresh")
        self.session_button_group.addButton(self.fresh_radio, 1)
        session_layout.addWidget(self.fresh_radio)

        # Fresh description
        fresh_desc = QLabel("Clear all missions and start a new hauling session")
        fresh_desc.setStyleSheet("color: #888; font-size: 11px; margin-left: 25px;")
        session_layout.addWidget(fresh_desc)

        # If no active missions, select fresh by default
        if not self.has_active_missions:
            self.fresh_radio.setChecked(True)
            self.continue_radio.setEnabled(False)

        layout.addWidget(session_group)

        # Spacer
        layout.addStretch()

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.start_button = QPushButton("Start Hauling")
        self.start_button.setMinimumWidth(150)
        self.start_button.setMinimumHeight(40)
        self.start_button.setProperty("class", "primary")
        self.start_button.clicked.connect(self._on_start)
        button_layout.addWidget(self.start_button)

        layout.addLayout(button_layout)

        # Trigger initial ship info update
        self._on_ship_changed(self.ship_combo.currentIndex())

    def _load_last_settings(self):
        """Load last used ship from config."""
        last_ship = self.config.get("route_planner", "selected_ship", default="")

        if last_ship:
            # Find and select the last used ship
            for i in range(self.ship_combo.count()):
                if self.ship_combo.itemData(i) == last_ship:
                    self.ship_combo.setCurrentIndex(i)
                    logger.debug(f"Restored last ship selection: {last_ship}")
                    break
        else:
            # Default to a common ship if no previous selection
            default_ships = ["CRUSADER_C2_HERCULES", "MISC_FREELANCER_MAX", "DRAKE_CUTLASS_BLACK"]
            for default in default_ships:
                for i in range(self.ship_combo.count()):
                    if self.ship_combo.itemData(i) == default:
                        self.ship_combo.setCurrentIndex(i)
                        break
                else:
                    continue
                break

    def _on_ship_changed(self, index: int):
        """Handle ship selection change."""
        ship_key = self.ship_combo.itemData(index)
        if ship_key and ship_key in SHIP_PROFILES:
            ship = SHIP_PROFILES[ship_key]
            info_text = ship.description
            if not ship.can_land_on_outposts:
                info_text += " | Cannot land on outposts"
            if not ship.can_land_on_stations:
                info_text += " | Requires station docking"
            self.ship_info_label.setText(info_text)

    def _on_start(self):
        """Handle start button click."""
        self.selected_ship_key = self.ship_combo.currentData()
        self.start_fresh = self.fresh_radio.isChecked()

        # Save ship selection to config
        self.config.set("route_planner", "selected_ship", value=self.selected_ship_key)

        # Also update ship capacity based on selection
        if self.selected_ship_key in SHIP_PROFILES:
            ship = SHIP_PROFILES[self.selected_ship_key]
            self.config.set("route_planner", "ship_capacity", value=ship.cargo_capacity_scu)

        self.config.save()

        logger.info(f"Session started - Ship: {self.selected_ship_key}, Fresh start: {self.start_fresh}")
        self.accept()

    def get_ship_key(self) -> str:
        """Get the selected ship key."""
        return self.selected_ship_key

    def get_ship_capacity(self) -> int:
        """Get the selected ship's cargo capacity."""
        if self.selected_ship_key in SHIP_PROFILES:
            return SHIP_PROFILES[self.selected_ship_key].cargo_capacity_scu
        return 128  # Default fallback

    def should_start_fresh(self) -> bool:
        """Check if user wants to start fresh."""
        return self.start_fresh
