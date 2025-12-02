"""
Mission validation and editing form for PyQt6.

Allows users to review and correct extracted mission data before saving.
"""

from typing import Optional, List
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QLineEdit, QSpinBox, QPushButton, QCompleter, QLabel,
    QScrollArea, QFrame, QProgressBar
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIntValidator

from src.location_autocomplete import LocationMatcher
from src.cargo_autocomplete import CargoMatcher
from src.domain.models import Mission, Objective
from src.services.mission_synergy_analyzer import MissionSynergyAnalyzer, SynergyMetrics
from src.logger import get_logger

logger = get_logger()


class ObjectiveRow(QWidget):
    """Single objective row with autocomplete."""

    removed = pyqtSignal(object)  # Emits self when remove button clicked

    def __init__(self, location_matcher: LocationMatcher, cargo_matcher: CargoMatcher):
        super().__init__()

        self.location_matcher = location_matcher
        self.cargo_matcher = cargo_matcher

        self._setup_ui()

    def _setup_ui(self):
        """Setup the objective row UI."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Collection location
        self.collect_edit = QLineEdit()
        self.collect_edit.setPlaceholderText("Collection location...")
        self.collect_edit.setMinimumWidth(180)
        self._setup_location_autocomplete(self.collect_edit)
        layout.addWidget(QLabel("From:"))
        layout.addWidget(self.collect_edit, 2)

        # Cargo type
        self.cargo_edit = QLineEdit()
        self.cargo_edit.setPlaceholderText("Cargo type...")
        self.cargo_edit.setMinimumWidth(150)
        self._setup_cargo_autocomplete(self.cargo_edit)
        layout.addWidget(QLabel("Cargo:"))
        layout.addWidget(self.cargo_edit, 1)

        # SCU amount with vertical +/- buttons
        layout.addWidget(QLabel("SCU:"))

        scu_container = QHBoxLayout()
        scu_container.setSpacing(2)
        scu_container.setContentsMargins(0, 0, 0, 0)

        self.scu_spin = QSpinBox()
        self.scu_spin.setRange(1, 9999)
        self.scu_spin.setValue(1)
        self.scu_spin.setMinimumWidth(50)
        self.scu_spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        scu_container.addWidget(self.scu_spin)

        # Vertical button widget (fixed size container)
        btn_widget = QWidget()
        btn_widget.setFixedSize(20, 30)
        btn_layout = QVBoxLayout(btn_widget)
        btn_layout.setSpacing(1)
        btn_layout.setContentsMargins(0, 0, 0, 0)

        scu_up_btn = QPushButton("+")
        scu_up_btn.setFixedSize(20, 14)
        scu_up_btn.setStyleSheet("padding: 0px; font-size: 10px;")
        scu_up_btn.clicked.connect(lambda: self.scu_spin.setValue(self.scu_spin.value() + 1))
        btn_layout.addWidget(scu_up_btn)

        scu_down_btn = QPushButton("-")
        scu_down_btn.setFixedSize(20, 14)
        scu_down_btn.setStyleSheet("padding: 0px; font-size: 10px;")
        scu_down_btn.clicked.connect(lambda: self.scu_spin.setValue(self.scu_spin.value() - 1))
        btn_layout.addWidget(scu_down_btn)

        scu_container.addWidget(btn_widget)
        layout.addLayout(scu_container)

        # Delivery location
        self.deliver_edit = QLineEdit()
        self.deliver_edit.setPlaceholderText("Delivery location...")
        self.deliver_edit.setMinimumWidth(180)
        self._setup_location_autocomplete(self.deliver_edit)
        layout.addWidget(QLabel("To:"))
        layout.addWidget(self.deliver_edit, 2)

        # Remove button
        self.remove_btn = QPushButton("X")
        self.remove_btn.setFixedSize(28, 28)
        self.remove_btn.setStyleSheet("""
            QPushButton { background-color: #d32f2f; padding: 0px; }
            QPushButton:hover { background-color: #f44336; }
        """)
        self.remove_btn.setToolTip("Remove objective")
        self.remove_btn.clicked.connect(lambda: self.removed.emit(self))
        layout.addWidget(self.remove_btn)

    def _setup_location_autocomplete(self, line_edit: QLineEdit):
        """Setup location autocomplete for a line edit."""
        locations = self.location_matcher.get_all_locations()
        completer = QCompleter(locations)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        line_edit.setCompleter(completer)

    def _setup_cargo_autocomplete(self, line_edit: QLineEdit):
        """Setup cargo type autocomplete for a line edit."""
        cargo_types = self.cargo_matcher.get_all_cargo_types()
        completer = QCompleter(cargo_types)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        line_edit.setCompleter(completer)

    def get_data(self) -> dict:
        """Get objective data with normalized location names."""
        collect_from = self.collect_edit.text().strip()
        deliver_to = self.deliver_edit.text().strip()

        # Normalize location names to canonical forms
        if collect_from:
            collect_from = self.location_matcher.normalize_location(collect_from)
        if deliver_to:
            deliver_to = self.location_matcher.normalize_location(deliver_to)

        return {
            "collect_from": collect_from,
            "cargo_type": self.cargo_edit.text().strip(),
            "scu_amount": self.scu_spin.value(),
            "deliver_to": deliver_to
        }

    def set_data(self, data: dict):
        """Set objective data."""
        self.collect_edit.setText(data.get("collect_from", ""))
        self.cargo_edit.setText(data.get("cargo_type", "Unknown"))
        self.scu_spin.setValue(data.get("scu_amount", 1))
        self.deliver_edit.setText(data.get("deliver_to", ""))

    def is_valid(self) -> tuple[bool, str]:
        """Validate objective data."""
        if not self.collect_edit.text().strip():
            return False, "Collection location is required"
        if not self.cargo_edit.text().strip():
            return False, "Cargo type is required"
        if not self.deliver_edit.text().strip():
            return False, "Delivery location is required"
        if self.scu_spin.value() <= 0:
            return False, "SCU amount must be greater than 0"
        return True, ""


class ValidationForm(QWidget):
    """Mission validation and editing form."""

    mission_saved = pyqtSignal(dict)  # Emits mission data when saved

    def __init__(
        self,
        location_matcher: LocationMatcher,
        cargo_matcher: CargoMatcher,
        get_active_missions_callback=None,
        synergy_config: Optional[dict] = None
    ):
        super().__init__()

        self.location_matcher = location_matcher
        self.cargo_matcher = cargo_matcher
        self.objective_rows = []
        self.get_active_missions_callback = get_active_missions_callback

        # Synergy configuration
        self.synergy_config = synergy_config or {
            'enabled': True,
            'ship_capacity': 128.0,
            'capacity_warning_threshold': 80.0,
            'low_synergy_threshold': 30.0,
            'check_timing': True,
            'show_route_preview': True,
            'show_recommendations': True
        }

        self.current_synergy_metrics: Optional[SynergyMetrics] = None
        self.current_mission_data: Optional[dict] = None

        self._setup_ui()

    def _setup_ui(self):
        """Setup the validation form UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Mission details group
        self.details_group = QGroupBox("Mission Details")
        details_layout = QGridLayout()
        details_layout.setSpacing(6)

        # Hauling mission ranks (Star Citizen 4.4)
        self.HAULING_RANKS = [
            "Trainee", "Rookie", "Junior", "Member",
            "Experienced", "Senior", "Master"
        ]

        # Hauling contractors (Star Citizen 4.4)
        self.HAULING_CONTRACTORS = [
            "Covalex Shipping", "Ling Family Hauling", "Red Wind Linehaul"
        ]

        # Row 0: Contracted By | Rank
        contracted_label = QLabel("Contracted By:")
        contracted_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        details_layout.addWidget(contracted_label, 0, 0)

        self.contracted_by_edit = QLineEdit()
        self.contracted_by_edit.setPlaceholderText("e.g., Covalex Shipping")
        contractor_completer = QCompleter(self.HAULING_CONTRACTORS)
        contractor_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        contractor_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.contracted_by_edit.setCompleter(contractor_completer)
        details_layout.addWidget(self.contracted_by_edit, 0, 1)

        rank_label = QLabel("Rank:")
        rank_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        details_layout.addWidget(rank_label, 0, 2)

        self.rank_edit = QLineEdit()
        self.rank_edit.setPlaceholderText("e.g., Rookie")
        rank_completer = QCompleter(self.HAULING_RANKS)
        rank_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.rank_edit.setCompleter(rank_completer)
        details_layout.addWidget(self.rank_edit, 0, 3)

        # Row 1: Reward | Time Left
        reward_label = QLabel("Reward (aUEC):")
        reward_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        details_layout.addWidget(reward_label, 1, 0)

        self.reward_edit = QLineEdit()
        self.reward_edit.setPlaceholderText("e.g., 48500")
        self.reward_edit.setValidator(QIntValidator(0, 999999999))
        details_layout.addWidget(self.reward_edit, 1, 1)

        time_label = QLabel("Time Left:")
        time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        details_layout.addWidget(time_label, 1, 2)

        self.availability_edit = QLineEdit()
        self.availability_edit.setPlaceholderText("HH:MM:SS")
        details_layout.addWidget(self.availability_edit, 1, 3)

        # Set column stretch so fields expand evenly
        details_layout.setColumnStretch(1, 1)
        details_layout.setColumnStretch(3, 1)

        self.details_group.setLayout(details_layout)
        layout.addWidget(self.details_group)

        # Objectives group
        self.objectives_group = QGroupBox("Cargo Objectives")
        objectives_group_layout = QVBoxLayout()
        objectives_group_layout.setContentsMargins(8, 8, 8, 8)
        objectives_group_layout.setSpacing(4)

        # Scrollable area for objectives (includes the add button row)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMinimumHeight(80)

        scroll_widget = QWidget()
        scroll_widget.setStyleSheet("background-color: #252525;")
        self.objectives_layout = QVBoxLayout(scroll_widget)
        self.objectives_layout.setContentsMargins(0, 0, 0, 0)
        self.objectives_layout.setSpacing(8)
        self.objectives_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Add objective button styled like an objective row (inside scroll area)
        self.add_obj_btn = QPushButton("+ Add Objective")
        self.add_obj_btn.setProperty("class", "secondary")
        self.add_obj_btn.setMinimumHeight(32)
        self.add_obj_btn.clicked.connect(self._add_objective_row)
        self.objectives_layout.addWidget(self.add_obj_btn)

        scroll.setWidget(scroll_widget)
        scroll.setAlignment(Qt.AlignmentFlag.AlignTop)
        objectives_group_layout.addWidget(scroll)

        self.objectives_group.setLayout(objectives_group_layout)
        layout.addWidget(self.objectives_group)

        # Synergy analysis section
        if self.synergy_config.get('enabled', True):
            synergy_group = QGroupBox("Mission Synergy")
            synergy_layout = QVBoxLayout()
            synergy_layout.setSpacing(6)

            # Stats row
            self.synergy_stats_label = QLabel("Waiting for mission data...")
            self.synergy_stats_label.setWordWrap(True)
            synergy_layout.addWidget(self.synergy_stats_label)

            # Synergy progress bar
            bar_layout = QHBoxLayout()
            bar_layout.setSpacing(8)

            self.synergy_bar = QProgressBar()
            self.synergy_bar.setRange(0, 100)
            self.synergy_bar.setValue(0)
            self.synergy_bar.setTextVisible(True)
            self.synergy_bar.setFormat("%p%")
            self.synergy_bar.setMinimumHeight(24)
            self.synergy_bar.setStyleSheet("""
                QProgressBar {
                    border: 1px solid #404040;
                    border-radius: 4px;
                    background-color: #2d2d2d;
                    text-align: center;
                    color: #ffffff;
                    font-weight: bold;
                }
                QProgressBar::chunk {
                    border-radius: 3px;
                    background-color: #4caf50;
                }
            """)
            bar_layout.addWidget(self.synergy_bar)

            synergy_layout.addLayout(bar_layout)

            # Verdict label
            self.synergy_verdict_label = QLabel()
            self.synergy_verdict_label.setWordWrap(True)
            synergy_layout.addWidget(self.synergy_verdict_label)

            synergy_group.setLayout(synergy_layout)
            layout.addWidget(synergy_group)
            self.synergy_group = synergy_group
        else:
            self.synergy_group = None

        # Action buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        clear_btn = QPushButton("Clear")
        clear_btn.setProperty("class", "secondary")
        clear_btn.clicked.connect(self.clear)
        button_layout.addWidget(clear_btn)

        save_btn = QPushButton("Add to Hauling List")
        save_btn.clicked.connect(self._save_mission)
        button_layout.addWidget(save_btn)

        layout.addLayout(button_layout)

        # Add initial objective row
        self._add_objective_row()

    def _add_objective_row(self):
        """Add a new objective row."""
        row = ObjectiveRow(self.location_matcher, self.cargo_matcher)
        row.removed.connect(self._remove_objective_row)

        # Insert before the "Add Objective" button (which is at the end)
        insert_index = self.objectives_layout.count() - 1
        self.objectives_layout.insertWidget(insert_index, row)
        self.objective_rows.append(row)

        logger.debug(f"Added objective row (total: {len(self.objective_rows)})")

    def _remove_objective_row(self, row: ObjectiveRow):
        """Remove an objective row."""
        if len(self.objective_rows) > 1:  # Keep at least one row
            self.objective_rows.remove(row)
            row.deleteLater()
            logger.debug(f"Removed objective row (remaining: {len(self.objective_rows)})")

    def load_data(self, mission_data: dict):
        """Load mission data into the form."""
        # Clear existing
        self.clear()

        # Store current mission data
        self.current_mission_data = mission_data

        # Load mission details
        self.rank_edit.setText(mission_data.get("rank", ""))
        self.contracted_by_edit.setText(mission_data.get("contracted_by", ""))
        self.reward_edit.setText(str(mission_data.get("reward", "")))
        self.availability_edit.setText(mission_data.get("availability", ""))

        # Load objectives
        objectives = mission_data.get("objectives", [])
        for obj_data in objectives:
            if not self.objective_rows:
                self._add_objective_row()

            row = self.objective_rows[-1]
            row.set_data(obj_data)

            # Add new row for next objective if needed
            if obj_data != objectives[-1]:
                self._add_objective_row()

        logger.info("Mission data loaded into validation form")

        # Analyze synergy with active missions
        if self.synergy_config.get('enabled', True):
            self._analyze_synergy(mission_data)

    def clear(self):
        """Clear the form."""
        self.rank_edit.clear()
        self.contracted_by_edit.clear()
        self.reward_edit.clear()
        self.availability_edit.clear()

        # Remove all but one objective row
        while len(self.objective_rows) > 1:
            row = self.objective_rows.pop()
            row.deleteLater()

        # Clear the remaining row
        if self.objective_rows:
            self.objective_rows[0].collect_edit.clear()
            self.objective_rows[0].cargo_edit.clear()
            self.objective_rows[0].scu_spin.setValue(1)
            self.objective_rows[0].deliver_edit.clear()

        logger.debug("Validation form cleared")

    def _save_mission(self):
        """Validate and save the mission."""
        # Validate reward
        reward_text = self.reward_edit.text().strip()
        if not reward_text:
            self._show_error("Reward is required")
            return

        try:
            reward = int(reward_text)
        except ValueError:
            self._show_error("Reward must be a valid number")
            return

        # Validate availability
        availability = self.availability_edit.text().strip()
        if not availability:
            self._show_error("Availability time is required")
            return

        # Validate objectives
        objectives = []
        for i, row in enumerate(self.objective_rows):
            valid, error = row.is_valid()
            if not valid:
                self._show_error(f"Objective {i+1}: {error}")
                return

            obj_data = row.get_data()
            # Skip empty objectives
            if obj_data["collect_from"] and obj_data["deliver_to"]:
                objectives.append(obj_data)

        if not objectives:
            self._show_error("At least one objective is required")
            return

        # Build mission data
        mission_data = {
            "reward": reward,
            "availability": availability,
            "objectives": objectives
        }

        # Add optional fields if present
        rank = self.rank_edit.text().strip()
        if rank:
            mission_data["rank"] = rank

        contracted_by = self.contracted_by_edit.text().strip()
        if contracted_by:
            mission_data["contracted_by"] = contracted_by

        # Emit signal
        self.mission_saved.emit(mission_data)
        logger.info("Mission validated and saved")

    def _analyze_synergy(self, mission_data: dict):
        """Analyze synergy with active missions and update display."""
        if not self.synergy_group:
            return

        # Get active missions
        active_missions = []
        if self.get_active_missions_callback:
            try:
                active_missions = self.get_active_missions_callback()
            except Exception as e:
                logger.error(f"Error getting active missions: {e}")
                self.synergy_stats_label.setText("Unable to analyze synergy")
                return

        # If no active missions, show neutral message
        if not active_missions:
            self.synergy_stats_label.setText("First mission - no comparison needed")
            self.synergy_bar.setValue(100)
            self._set_bar_color("green")
            self.synergy_verdict_label.setText("")
            return

        # Convert mission_data to Mission object
        try:
            objectives = [
                Objective(
                    collect_from=obj.get('collect_from', ''),
                    deliver_to=obj.get('deliver_to', ''),
                    scu_amount=obj.get('scu_amount', 0),
                    cargo_type=obj.get('cargo_type', 'Unknown')
                )
                for obj in mission_data.get('objectives', [])
            ]

            candidate_mission = Mission(
                id='candidate',
                reward=float(mission_data.get('reward', 0)),
                availability=mission_data.get('availability', '00:00:00'),
                objectives=objectives,
                timestamp='',
                status='active'
            )
        except Exception as e:
            logger.error(f"Error creating candidate mission: {e}")
            self.synergy_stats_label.setText("Unable to analyze - invalid data")
            return

        # Create analyzer
        analyzer = MissionSynergyAnalyzer(
            ship_capacity=self.synergy_config.get('ship_capacity', 128.0),
            capacity_threshold_pct=self.synergy_config.get('capacity_warning_threshold', 80.0)
        )

        # Analyze
        try:
            metrics = analyzer.analyze(candidate_mission, active_missions)
            self.current_synergy_metrics = metrics

            # Update display
            self._update_synergy_display(metrics)

        except Exception as e:
            logger.error(f"Error analyzing synergy: {e}")
            self.synergy_stats_label.setText(f"Error: {str(e)}")

    def _update_synergy_display(self, metrics: SynergyMetrics):
        """Update synergy display with metrics."""
        # Build stats text
        stats_parts = []

        # Stop breakdown
        if metrics.shared_stops > 0:
            stats_parts.append(f"Shared: {metrics.shared_stops}")
        if metrics.nearby_stops > 0:
            stats_parts.append(f"Nearby: {metrics.nearby_stops}")
        if metrics.new_stops > 0:
            stats_parts.append(f"New: {metrics.new_stops}")

        # Capacity info
        capacity_pct = (metrics.total_scu / metrics.ship_capacity * 100) if metrics.ship_capacity > 0 else 0
        stats_parts.append(f"Capacity: {metrics.total_scu:.0f}/{metrics.ship_capacity:.0f} SCU ({capacity_pct:.0f}%)")

        self.synergy_stats_label.setText(" | ".join(stats_parts))

        # Update progress bar
        score = int(metrics.synergy_score)
        self.synergy_bar.setValue(score)
        self._set_bar_color(metrics.verdict_color)

        # Update verdict
        self.synergy_verdict_label.setText(metrics.verdict)
        color_map = {
            "green": "#4caf50",
            "yellow": "#ffeb3b",
            "orange": "#ff9800",
            "red": "#d32f2f"
        }
        verdict_color = color_map.get(metrics.verdict_color, "#e0e0e0")
        self.synergy_verdict_label.setStyleSheet(f"color: {verdict_color}; font-weight: bold;")

    def _set_bar_color(self, color: str):
        """Set the synergy bar color."""
        color_map = {
            "green": "#4caf50",
            "yellow": "#ffeb3b",
            "orange": "#ff9800",
            "red": "#d32f2f"
        }
        bar_color = color_map.get(color, "#4caf50")
        self.synergy_bar.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid #404040;
                border-radius: 4px;
                background-color: #2d2d2d;
                text-align: center;
                color: #ffffff;
                font-weight: bold;
            }}
            QProgressBar::chunk {{
                border-radius: 3px;
                background-color: {bar_color};
            }}
        """)

    def _show_error(self, message: str):
        """Show validation error."""
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.warning(self, "Validation Error", message)
