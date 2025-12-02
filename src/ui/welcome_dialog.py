"""
Welcome dialog shown on application startup.

Allows users to select their ship and choose whether to continue
their previous session or start fresh.
"""

from typing import List, Dict, Any

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QGroupBox, QFrame
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from src.config import Config
from src.ship_profiles import SHIP_PROFILES, ShipProfile
from src.ui.styles import get_stylesheet
from src.logger import get_logger

logger = get_logger()


class WelcomeDialog(QDialog):
    """
    Welcome dialog for session setup.

    Allows selecting ship and choosing to continue or start fresh.
    """

    def __init__(self, config: Config, active_missions: List[Dict[str, Any]], parent=None):
        super().__init__(parent)
        self.config = config
        self.active_missions = active_missions
        self.has_active_missions = len(active_missions) > 0

        self.selected_ship_key: str = ""
        self.start_fresh: bool = False

        self._setup_ui()
        self._load_last_settings()

    def _setup_ui(self):
        """Initialize the dialog UI."""
        self.setWindowTitle("SC Hauling Assistant")
        self.setMinimumWidth(450)
        self.setModal(True)

        # Apply app stylesheet to dialog
        self.setStyleSheet(get_stylesheet())

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

        # Sort ships alphabetically by display name
        ships_sorted = sorted(
            SHIP_PROFILES.items(),
            key=lambda x: x[1].display_name
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

        # Spacer
        layout.addStretch()

        # Session buttons - two big action buttons
        session_label = QLabel("Start Session")
        session_label.setStyleSheet("font-weight: bold; font-size: 13px; margin-top: 10px;")
        layout.addWidget(session_label)

        # Continue Session button (if has active missions)
        self.continue_btn = QPushButton("Continue Session")
        self.continue_btn.setMinimumHeight(50)
        self.continue_btn.setProperty("class", "primary")
        self.continue_btn.clicked.connect(self._on_continue)

        if self.has_active_missions:
            summary = self._get_session_summary()
            self.continue_btn.setText(f"Continue Session\n{summary}")
        else:
            self.continue_btn.setText("Continue Session\nNo active missions")
            self.continue_btn.setEnabled(False)
            self.continue_btn.setProperty("class", "secondary")

        layout.addWidget(self.continue_btn)

        # Start Fresh button
        self.fresh_btn = QPushButton("Start Fresh\nClear all missions and start new")
        self.fresh_btn.setMinimumHeight(50)
        self.fresh_btn.setProperty("class", "secondary")
        self.fresh_btn.clicked.connect(self._on_fresh)
        layout.addWidget(self.fresh_btn)

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

    def _get_session_summary(self) -> str:
        """Calculate summary of remaining work from active missions."""
        if not self.active_missions:
            return ""

        total_missions = len(self.active_missions)
        total_scu = 0
        total_stops = 0

        for mission in self.active_missions:
            objectives = mission.get("objectives", [])
            for obj in objectives:
                scu = obj.get("scu_amount", 0)
                total_scu += scu

                # Count stops (pickup + delivery = 2 stops per objective)
                pickup_done = obj.get("pickup_completed", False)
                delivery_done = obj.get("delivery_completed", False)

                if not pickup_done:
                    total_stops += 1
                if not delivery_done:
                    total_stops += 1

        # Build summary string
        parts = []
        parts.append(f"{total_missions} mission{'s' if total_missions != 1 else ''}")
        parts.append(f"{total_stops} stop{'s' if total_stops != 1 else ''}")
        parts.append(f"{total_scu:,} SCU")

        return " | ".join(parts)

    def _save_ship_config(self):
        """Save ship selection to config."""
        self.selected_ship_key = self.ship_combo.currentData()

        # Save ship selection to config
        self.config.set("route_planner", "selected_ship", value=self.selected_ship_key)

        # Also update ship capacity based on selection
        if self.selected_ship_key in SHIP_PROFILES:
            ship = SHIP_PROFILES[self.selected_ship_key]
            self.config.set("route_planner", "ship_capacity", value=ship.cargo_capacity_scu)

        self.config.save()

    def _on_continue(self):
        """Handle continue session button click."""
        self._save_ship_config()
        self.start_fresh = False
        logger.info(f"Session continued - Ship: {self.selected_ship_key}")
        self.accept()

    def _on_fresh(self):
        """Handle start fresh button click."""
        self._save_ship_config()
        self.start_fresh = True
        logger.info(f"Fresh session started - Ship: {self.selected_ship_key}")
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
