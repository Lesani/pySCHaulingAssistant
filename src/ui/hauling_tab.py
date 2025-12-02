"""
Hauling tab for PyQt6.

Mission management with table view, sorting, grouping, and route optimization.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QPushButton, QComboBox, QLabel, QMenu, QMessageBox, QSplitter,
    QTextEdit, QHeaderView, QGroupBox, QDialog
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QFont

from src.config import Config
from src.mission_manager import MissionManager
from src.location_autocomplete import LocationMatcher
from src.cargo_autocomplete import CargoMatcher
from src.route_optimizer import RouteOptimizer
from src.ui.validation_form import ValidationForm
from src.logger import get_logger

logger = get_logger()


class EditMissionDialog(QDialog):
    """Dialog for editing an existing mission."""

    def __init__(self, mission: dict, mission_manager: MissionManager,
                 location_matcher: LocationMatcher, cargo_matcher: CargoMatcher,
                 parent=None):
        super().__init__(parent)

        self.mission = mission
        self.mission_manager = mission_manager
        self.mission_id = mission.get("id")

        self.setWindowTitle("Edit Mission")
        self.setMinimumWidth(1000)
        self.setMinimumHeight(600)
        self.resize(1000, 700)

        self._setup_ui(location_matcher, cargo_matcher)
        self._load_mission_data()

    def _setup_ui(self, location_matcher: LocationMatcher, cargo_matcher: CargoMatcher):
        """Setup the dialog UI."""
        layout = QVBoxLayout(self)

        # Validation form (without synergy analysis for editing)
        synergy_config = {'enabled': False}
        self.validation_form = ValidationForm(
            location_matcher,
            cargo_matcher,
            synergy_config=synergy_config
        )

        # Replace the save button text
        # Find the save button and change its text
        for child in self.validation_form.findChildren(QPushButton):
            if child.text() == "Add to Hauling List":
                child.setText("Save Changes")
                break

        # Connect mission saved signal
        self.validation_form.mission_saved.connect(self._on_mission_saved)

        layout.addWidget(self.validation_form)

        # Dialog buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setProperty("class", "secondary")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        layout.addLayout(button_layout)

    def _load_mission_data(self):
        """Load the mission data into the form."""
        self.validation_form.load_data(self.mission)

    def _on_mission_saved(self, mission_data: dict):
        """Handle mission data saved from validation form."""
        try:
            # Update the existing mission
            self.mission_manager.update_mission(self.mission_id, mission_data)
            logger.info(f"Updated mission {self.mission_id}")

            # Close dialog with accepted status
            self.accept()

        except Exception as e:
            logger.error(f"Failed to update mission: {e}")
            QMessageBox.critical(
                self,
                "Update Error",
                f"Failed to update mission:\n{str(e)}"
            )


class HaulingTab(QWidget):
    """Hauling missions management tab."""

    def __init__(self, config: Config, mission_manager: MissionManager,
                 location_matcher: LocationMatcher, cargo_matcher: CargoMatcher = None):
        super().__init__()

        self.config = config
        self.mission_manager = mission_manager
        self.location_matcher = location_matcher
        self.cargo_matcher = cargo_matcher or CargoMatcher()

        # State
        self.current_sort = config.get("hauling", "last_sort", default="reward")
        self.sort_ascending = config.get("hauling", "sort_ascending", default=False)
        self.current_group = config.get("hauling", "last_group", default="none")

        self._setup_ui()
        self.refresh()

    def _setup_ui(self):
        """Setup the hauling tab UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        # Group selector
        toolbar.addWidget(QLabel("Group by:"))
        self.group_combo = QComboBox()
        self.group_combo.addItems(["None", "Source", "Destination"])
        self.group_combo.setCurrentText(self.current_group.capitalize())
        self.group_combo.currentTextChanged.connect(self._on_group_changed)
        toolbar.addWidget(self.group_combo)

        toolbar.addSpacing(20)

        # Action buttons
        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.setProperty("class", "secondary")
        refresh_btn.clicked.connect(self.refresh)
        toolbar.addWidget(refresh_btn)

        export_btn = QPushButton("📤 Export")
        export_btn.setProperty("class", "secondary")
        export_btn.clicked.connect(self._export_missions)
        toolbar.addWidget(export_btn)

        clear_btn = QPushButton("🗑️ Clear All")
        clear_btn.setProperty("class", "danger")
        clear_btn.clicked.connect(self._clear_all)
        toolbar.addWidget(clear_btn)

        toolbar.addStretch()

        layout.addLayout(toolbar)

        # Splitter for missions table and route panel
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Missions tree
        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["Mission Details", "Reward", "Time Left", "Status"])
        self.tree.setSortingEnabled(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.tree.itemDoubleClicked.connect(self._view_details)

        # Column widths
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)

        # Connect header clicks for sorting
        header.sectionClicked.connect(self._on_column_clicked)

        splitter.addWidget(self.tree)

        # Route suggestions panel
        route_group = QGroupBox("Route Suggestions")
        route_layout = QVBoxLayout()

        self.route_text = QTextEdit()
        self.route_text.setReadOnly(True)
        self.route_text.setMinimumWidth(300)
        route_layout.addWidget(self.route_text)

        route_group.setLayout(route_layout)
        splitter.addWidget(route_group)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)

        layout.addWidget(splitter)

        # Summary label
        self.summary_label = QLabel()
        self.summary_label.setProperty("class", "muted")
        layout.addWidget(self.summary_label)

    def refresh(self):
        """Refresh missions display."""
        self.tree.clear()

        # Get active missions
        missions = self.mission_manager.get_missions(status="active")

        if not missions:
            self._update_summary([], 0, 0)
            self.route_text.setPlainText("No active missions")
            return

        # Apply grouping
        if self.current_group == "source":
            self._display_grouped_by_source(missions)
        elif self.current_group == "destination":
            self._display_grouped_by_destination(missions)
        else:
            self._display_flat(missions)

        # Update route suggestions
        self._update_route_suggestions(missions)

        # Update summary
        total_missions = len(missions)
        total_reward = sum(m.get("reward", 0) for m in missions)
        total_scu = sum(
            sum(obj.get("scu_amount", 0) for obj in m.get("objectives", []))
            for m in missions
        )
        self._update_summary(missions, total_reward, total_scu)

        logger.info(f"Refreshed hauling tab: {total_missions} active missions")

    def _display_flat(self, missions: list):
        """Display missions in flat list."""
        for mission in missions:
            self._add_mission_item(self.tree, mission)

    def _display_grouped_by_source(self, missions: list):
        """Display missions grouped by source location."""
        groups = RouteOptimizer.group_by_source(missions)

        for source, group_missions in sorted(groups.items()):
            # Create group item
            group_item = QTreeWidgetItem(self.tree)
            totals = RouteOptimizer.calculate_group_totals(group_missions)

            group_item.setText(0, f"📍 {source}")
            group_item.setText(1, f"{totals['reward']:,} aUEC")
            group_item.setText(2, f"{totals['scu']} SCU")
            group_item.setText(3, f"{totals['missions']} missions")

            # Make group bold
            font = group_item.font(0)
            font.setBold(True)
            for col in range(4):
                group_item.setFont(col, font)

            # Add missions to group
            for mission in group_missions:
                self._add_mission_item(group_item, mission)

            group_item.setExpanded(True)

    def _display_grouped_by_destination(self, missions: list):
        """Display missions grouped by destination location."""
        groups = RouteOptimizer.group_by_destination(missions)

        for dest, group_missions in sorted(groups.items()):
            # Create group item
            group_item = QTreeWidgetItem(self.tree)
            totals = RouteOptimizer.calculate_group_totals(group_missions)

            group_item.setText(0, f"📍 {dest}")
            group_item.setText(1, f"{totals['reward']:,} aUEC")
            group_item.setText(2, f"{totals['scu']} SCU")
            group_item.setText(3, f"{totals['missions']} missions")

            # Make group bold
            font = group_item.font(0)
            font.setBold(True)
            for col in range(4):
                group_item.setFont(col, font)

            # Add missions to group
            for mission in group_missions:
                self._add_mission_item(group_item, mission)

            group_item.setExpanded(True)

    def _add_mission_item(self, parent, mission: dict):
        """Add a mission item to tree."""
        item = QTreeWidgetItem(parent)

        # Store mission ID
        item.setData(0, Qt.ItemDataRole.UserRole, mission.get("id"))

        # Mission details
        objectives = mission.get("objectives", [])
        sources = ", ".join(set(obj.get("collect_from", "") for obj in objectives))
        destinations = ", ".join(set(obj.get("deliver_to", "") for obj in objectives))
        total_scu = sum(obj.get("scu_amount", 0) for obj in objectives)
        cargo_types = ", ".join(set(obj.get("cargo_type", "Unknown") for obj in objectives))

        details = f"{cargo_types} ({total_scu} SCU): {sources} → {destinations}"
        item.setText(0, details)

        # Reward
        reward = mission.get("reward", 0)
        item.setText(1, f"{reward:,} aUEC")
        item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # Availability
        availability = mission.get("availability", "")
        item.setText(2, availability)
        item.setTextAlignment(2, Qt.AlignmentFlag.AlignCenter)

        # Status
        status = mission.get("status", "active").capitalize()
        item.setText(3, status)
        item.setTextAlignment(3, Qt.AlignmentFlag.AlignCenter)

        # Color code by status
        if status.lower() == "completed":
            for col in range(4):
                item.setForeground(col, Qt.GlobalColor.darkGreen)
        elif status.lower() == "expired":
            for col in range(4):
                item.setForeground(col, Qt.GlobalColor.darkRed)

    def _update_route_suggestions(self, missions: list):
        """Update route suggestions panel."""
        if not missions:
            self.route_text.setPlainText("No active missions")
            return

        route = RouteOptimizer.suggest_route(missions)
        summary = RouteOptimizer.get_route_summary(route)

        self.route_text.setPlainText(summary)

    def _update_summary(self, missions: list, total_reward: int, total_scu: int):
        """Update summary label."""
        summary = f"{len(missions)} missions  |  {total_reward:,} aUEC total  |  {total_scu} SCU total"
        self.summary_label.setText(summary)

    def _on_group_changed(self, text: str):
        """Handle group selection change."""
        self.current_group = text.lower()

        # Save preference
        if "hauling" not in self.config.settings:
            self.config.settings["hauling"] = {}
        self.config.settings["hauling"]["last_group"] = self.current_group
        self.config.save()

        self.refresh()
        logger.debug(f"Group changed to: {self.current_group}")

    def _on_column_clicked(self, index: int):
        """Handle column header click for sorting."""
        column_map = {0: "details", 1: "reward", 2: "availability", 3: "status"}
        self.current_sort = column_map.get(index, "reward")

        # Toggle sort direction
        self.sort_ascending = not self.sort_ascending

        # Save preference
        if "hauling" not in self.config.settings:
            self.config.settings["hauling"] = {}
        self.config.settings["hauling"]["last_sort"] = self.current_sort
        self.config.settings["hauling"]["sort_ascending"] = self.sort_ascending
        self.config.save()

        logger.debug(f"Sort by {self.current_sort} ({'asc' if self.sort_ascending else 'desc'})")

    def _show_context_menu(self, position):
        """Show context menu for mission."""
        item = self.tree.itemAt(position)
        if not item:
            return

        mission_id = item.data(0, Qt.ItemDataRole.UserRole)
        if not mission_id:
            return  # Group item

        menu = QMenu(self)

        view_action = QAction("👁️ View Details", self)
        view_action.triggered.connect(self._view_details)
        menu.addAction(view_action)

        edit_action = QAction("✏️ Edit", self)
        edit_action.triggered.connect(self._edit_mission)
        menu.addAction(edit_action)

        delete_action = QAction("🗑️ Delete", self)
        delete_action.triggered.connect(self._delete_mission)
        menu.addAction(delete_action)

        menu.addSeparator()

        complete_action = QAction("✅ Mark Completed", self)
        complete_action.triggered.connect(lambda: self._update_status("completed"))
        menu.addAction(complete_action)

        expire_action = QAction("⏰ Mark Expired", self)
        expire_action.triggered.connect(lambda: self._update_status("expired"))
        menu.addAction(expire_action)

        active_action = QAction("🔄 Mark Active", self)
        active_action.triggered.connect(lambda: self._update_status("active"))
        menu.addAction(active_action)

        menu.exec(self.tree.viewport().mapToGlobal(position))

    def _get_selected_mission_id(self) -> str:
        """Get the selected mission ID."""
        items = self.tree.selectedItems()
        if not items:
            return None

        item = items[0]
        return item.data(0, Qt.ItemDataRole.UserRole)

    def _view_details(self, item=None):
        """View mission details."""
        mission_id = self._get_selected_mission_id()
        if not mission_id:
            return

        missions = self.mission_manager.get_missions()
        mission = next((m for m in missions if m.get("id") == mission_id), None)

        if mission:
            self._show_mission_dialog(mission)

    def _show_mission_dialog(self, mission: dict):
        """Show mission details in a dialog."""
        details = f"Reward: {mission.get('reward', 0):,} aUEC\n"
        details += f"Time Left: {mission.get('availability', 'N/A')}\n"
        details += f"Status: {mission.get('status', 'active').capitalize()}\n\n"
        details += "Objectives:\n"

        for i, obj in enumerate(mission.get("objectives", []), 1):
            cargo_type = obj.get('cargo_type', 'Unknown')
            details += f"{i}. {cargo_type} ({obj.get('scu_amount', 0)} SCU): {obj.get('collect_from', '')} → {obj.get('deliver_to', '')}\n"

        QMessageBox.information(self, "Mission Details", details)

    def _edit_mission(self):
        """Edit selected mission."""
        mission_id = self._get_selected_mission_id()
        if not mission_id:
            return

        # Get mission data
        missions = self.mission_manager.get_missions()
        mission = next((m for m in missions if m.get("id") == mission_id), None)

        if not mission:
            QMessageBox.warning(self, "Error", "Mission not found")
            return

        # Show edit dialog
        dialog = EditMissionDialog(
            mission=mission,
            mission_manager=self.mission_manager,
            location_matcher=self.location_matcher,
            cargo_matcher=self.cargo_matcher,
            parent=self
        )

        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()
            logger.info(f"Mission {mission_id} updated successfully")

    def _delete_mission(self):
        """Delete selected mission."""
        mission_id = self._get_selected_mission_id()
        if not mission_id:
            return

        reply = QMessageBox.question(
            self,
            "Delete Mission",
            "Are you sure you want to delete this mission?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.mission_manager.delete_mission(mission_id)
            self.refresh()
            logger.info(f"Deleted mission: {mission_id}")

    def _update_status(self, status: str):
        """Update mission status."""
        mission_id = self._get_selected_mission_id()
        if not mission_id:
            return

        self.mission_manager.update_status(mission_id, status)
        self.refresh()
        logger.info(f"Updated mission {mission_id} status to: {status}")

    def _clear_all(self):
        """Clear all missions."""
        reply = QMessageBox.question(
            self,
            "Clear All Missions",
            "Are you sure you want to delete all missions?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.mission_manager.clear_all()
            self.refresh()
            logger.info("Cleared all missions")

    def _export_missions(self):
        """Export missions to file."""
        # TODO: Implement export functionality
        QMessageBox.information(self, "Export", "Export functionality coming soon!")
