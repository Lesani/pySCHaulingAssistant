"""
Mission validation and editing form for PyQt6.

Allows users to review and correct extracted mission data before saving.
"""

from typing import Optional, List
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLineEdit, QSpinBox, QPushButton, QCompleter, QLabel,
    QScrollArea, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIntValidator

from src.location_autocomplete import LocationMatcher
from src.cargo_autocomplete import CargoMatcher
from src.domain.models import Mission, Objective
from src.services.mission_synergy_analyzer import MissionSynergyAnalyzer, SynergyMetrics
from src.ui.route_preview_dialog import RoutePreviewDialog
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

        # SCU amount
        self.scu_spin = QSpinBox()
        self.scu_spin.setRange(1, 9999)
        self.scu_spin.setValue(1)
        self.scu_spin.setMinimumWidth(80)
        layout.addWidget(QLabel("SCU:"))
        layout.addWidget(self.scu_spin)

        # Delivery location
        self.deliver_edit = QLineEdit()
        self.deliver_edit.setPlaceholderText("Delivery location...")
        self.deliver_edit.setMinimumWidth(180)
        self._setup_location_autocomplete(self.deliver_edit)
        layout.addWidget(QLabel("To:"))
        layout.addWidget(self.deliver_edit, 2)

        # Remove button
        self.remove_btn = QPushButton("❌")
        self.remove_btn.setMaximumWidth(30)
        self.remove_btn.setProperty("class", "danger")
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

        # Mission details group
        details_group = QGroupBox("Mission Details")
        details_layout = QHBoxLayout()

        # Rank (read-only, extracted by AI)
        rank_layout = QFormLayout()
        self.rank_edit = QLineEdit()
        self.rank_edit.setPlaceholderText("(extracted)")
        self.rank_edit.setMinimumWidth(100)
        self.rank_edit.setReadOnly(True)
        self.rank_edit.setStyleSheet("QLineEdit { background-color: #252525; }")
        rank_layout.addRow("Rank:", self.rank_edit)
        details_layout.addLayout(rank_layout)

        # Contracted By (read-only, extracted by AI)
        contracted_layout = QFormLayout()
        self.contracted_by_edit = QLineEdit()
        self.contracted_by_edit.setPlaceholderText("(extracted)")
        self.contracted_by_edit.setMinimumWidth(150)
        self.contracted_by_edit.setReadOnly(True)
        self.contracted_by_edit.setStyleSheet("QLineEdit { background-color: #252525; }")
        contracted_layout.addRow("Contracted By:", self.contracted_by_edit)
        details_layout.addLayout(contracted_layout)

        # Reward
        reward_layout = QFormLayout()
        self.reward_edit = QLineEdit()
        self.reward_edit.setPlaceholderText("e.g., 48500")
        self.reward_edit.setValidator(QIntValidator(0, 999999999))
        self.reward_edit.setMinimumWidth(120)
        reward_layout.addRow("Reward (aUEC):", self.reward_edit)
        details_layout.addLayout(reward_layout)

        # Availability
        avail_layout = QFormLayout()
        self.availability_edit = QLineEdit()
        self.availability_edit.setPlaceholderText("HH:MM:SS")
        self.availability_edit.setMinimumWidth(100)
        avail_layout.addRow("Time Left:", self.availability_edit)
        details_layout.addLayout(avail_layout)

        details_layout.addStretch()
        details_group.setLayout(details_layout)
        layout.addWidget(details_group)

        # Objectives group
        objectives_group = QGroupBox("Cargo Objectives")
        objectives_layout = QVBoxLayout()

        # Scrollable area for objectives
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMinimumHeight(150)

        scroll_widget = QWidget()
        self.objectives_layout = QVBoxLayout(scroll_widget)
        self.objectives_layout.setSpacing(8)
        self.objectives_layout.addStretch()

        scroll.setWidget(scroll_widget)
        objectives_layout.addWidget(scroll)

        # Add objective button
        add_obj_btn = QPushButton("+ Add Objective")
        add_obj_btn.setProperty("class", "secondary")
        add_obj_btn.clicked.connect(self._add_objective_row)
        objectives_layout.addWidget(add_obj_btn)

        objectives_group.setLayout(objectives_layout)
        layout.addWidget(objectives_group)

        # Synergy analysis section
        if self.synergy_config.get('enabled', True):
            synergy_group = QGroupBox("Mission Synergy Analysis")
            synergy_layout = QVBoxLayout()

            # Summary label
            self.synergy_summary_label = QLabel("Analyzing synergy with active missions...")
            self.synergy_summary_label.setWordWrap(True)
            synergy_layout.addWidget(self.synergy_summary_label)

            # Warnings label
            self.synergy_warnings_label = QLabel()
            self.synergy_warnings_label.setWordWrap(True)
            self.synergy_warnings_label.setStyleSheet("color: #ff6b6b; font-weight: bold;")
            self.synergy_warnings_label.hide()
            synergy_layout.addWidget(self.synergy_warnings_label)

            # Recommendation label
            self.synergy_recommendation_label = QLabel()
            self.synergy_recommendation_label.setWordWrap(True)
            self.synergy_recommendation_label.hide()
            synergy_layout.addWidget(self.synergy_recommendation_label)

            # Route preview button
            if self.synergy_config.get('show_route_preview', True):
                self.route_preview_btn = QPushButton("Show Route Preview")
                self.route_preview_btn.setProperty("class", "secondary")
                self.route_preview_btn.clicked.connect(self._show_route_preview)
                self.route_preview_btn.setEnabled(False)
                synergy_layout.addWidget(self.route_preview_btn)

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

        # Insert before stretch
        self.objectives_layout.insertWidget(
            len(self.objective_rows),
            row
        )
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
                self.synergy_summary_label.setText("Unable to analyze synergy - error getting active missions")
                return

        # If no active missions, show neutral message
        if not active_missions:
            self.synergy_summary_label.setText("No active missions to compare with. This will be your first mission!")
            self.synergy_warnings_label.hide()
            self.synergy_recommendation_label.hide()
            if hasattr(self, 'route_preview_btn'):
                self.route_preview_btn.setEnabled(False)
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
            self.synergy_summary_label.setText("Unable to analyze synergy - invalid mission data")
            return

        # Create analyzer
        analyzer = MissionSynergyAnalyzer(
            ship_capacity=self.synergy_config.get('ship_capacity', 128.0),
            capacity_threshold_pct=self.synergy_config.get('capacity_warning_threshold', 80.0),
            low_synergy_threshold=self.synergy_config.get('low_synergy_threshold', 30.0),
            check_timing=self.synergy_config.get('check_timing', True)
        )

        # Analyze
        try:
            metrics = analyzer.analyze(candidate_mission, active_missions)
            self.current_synergy_metrics = metrics

            # Update display
            self._update_synergy_display(metrics)

            # Enable route preview button
            if hasattr(self, 'route_preview_btn'):
                self.route_preview_btn.setEnabled(True)

        except Exception as e:
            logger.error(f"Error analyzing synergy: {e}")
            self.synergy_summary_label.setText(f"Error analyzing synergy: {str(e)}")

    def _update_synergy_display(self, metrics: SynergyMetrics):
        """Update synergy display with metrics."""
        # Update summary
        self.synergy_summary_label.setText(metrics.inline_summary)

        # Build warnings
        warnings = []
        if metrics.exceeds_capacity:
            warnings.append(f"⚠ EXCEEDS SHIP CAPACITY: {metrics.total_scu:.0f} SCU > {metrics.ship_capacity:.0f} SCU")
        elif metrics.exceeds_threshold:
            warnings.append(f"⚠ High capacity usage: {metrics.capacity_utilization_pct:.0f}% (threshold: {self.synergy_config.get('capacity_warning_threshold', 80)}%)")

        if metrics.timing_warning:
            warnings.append(f"⏰ {metrics.timing_warning}")

        if metrics.low_synergy and self.synergy_config.get('show_recommendations', True):
            warnings.append(f"ℹ Low synergy score: {metrics.synergy_score:.0f}%")

        if warnings:
            self.synergy_warnings_label.setText("\n".join(warnings))
            self.synergy_warnings_label.show()
        else:
            self.synergy_warnings_label.hide()

        # Update recommendation
        if self.synergy_config.get('show_recommendations', True):
            if metrics.recommendation == "accept":
                rec_text = f"✓ {metrics.recommendation_reason}"
                rec_color = "#51cf66"  # Green
            else:
                rec_text = f"⚠ {metrics.recommendation_reason}"
                rec_color = "#ffd43b"  # Yellow

            self.synergy_recommendation_label.setText(rec_text)
            self.synergy_recommendation_label.setStyleSheet(f"color: {rec_color}; font-weight: bold;")
            self.synergy_recommendation_label.show()
        else:
            self.synergy_recommendation_label.hide()

    def _show_route_preview(self):
        """Show route preview dialog."""
        if not self.current_mission_data or not self.get_active_missions_callback:
            return

        try:
            # Get active missions
            active_missions = self.get_active_missions_callback()

            # Create candidate mission
            objectives = [
                Objective(
                    collect_from=obj.get('collect_from', ''),
                    deliver_to=obj.get('deliver_to', ''),
                    scu_amount=obj.get('scu_amount', 0),
                    cargo_type=obj.get('cargo_type', 'Unknown')
                )
                for obj in self.current_mission_data.get('objectives', [])
            ]

            candidate_mission = Mission(
                id='candidate',
                reward=float(self.current_mission_data.get('reward', 0)),
                availability=self.current_mission_data.get('availability', '00:00:00'),
                objectives=objectives,
                timestamp='',
                status='active'
            )

            # Show dialog
            dialog = RoutePreviewDialog(
                candidate_mission=candidate_mission,
                active_missions=active_missions,
                ship_capacity=self.synergy_config.get('ship_capacity', 128.0),
                parent=self
            )
            dialog.exec()

        except Exception as e:
            logger.error(f"Error showing route preview: {e}")
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Route Preview Error", f"Could not generate route preview: {str(e)}")

    def _show_error(self, message: str):
        """Show validation error."""
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.warning(self, "Validation Error", message)
