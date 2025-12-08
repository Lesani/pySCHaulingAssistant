"""
Scan Database tab for PyQt6.

View and manage scanned missions stored in the local database.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QComboBox, QAbstractItemView, QProgressDialog,
    QApplication, QDialog, QDialogButtonBox, QCompleter, QLineEdit
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QBrush

from datetime import datetime
from typing import Optional, TYPE_CHECKING, List

from src.mission_scan_db import MissionScanDB
from src.sync_service import SyncService
from src.config import Config
from src.special_locations import SPECIAL_LOCATIONS
from src.logger import get_logger
from src.location_autocomplete import LocationMatcher

if TYPE_CHECKING:
    from src.discord_auth import DiscordAuth

logger = get_logger()

# Color for unsynced scans (light blue)
UNSYNCED_BG_COLOR = QColor(173, 216, 230, 80)  # Light blue with transparency


class ScanDatabaseTab(QWidget):
    """Tab for viewing and managing the scan database."""

    login_requested = pyqtSignal()  # Emitted when login is needed for sync

    def __init__(self, scan_db: MissionScanDB, config: Config = None, discord_auth: Optional["DiscordAuth"] = None,
                 location_matcher: Optional[LocationMatcher] = None):
        super().__init__()

        self.scan_db = scan_db
        self.config = config
        self.discord_auth = discord_auth
        self.sync_service = SyncService(config, discord_auth) if config else None
        self.location_matcher = location_matcher or LocationMatcher()

        self._setup_ui()
        self._load_initial_data()

    def _setup_ui(self):
        """Setup the scan database tab UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Top controls
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(8)

        controls_layout.addWidget(QLabel("Filter by Location:"))

        self.location_filter = QComboBox()
        self.location_filter.setMinimumWidth(200)
        self.location_filter.addItem("All Locations")
        self.location_filter.addItem("No Location")
        self.location_filter.currentIndexChanged.connect(self._on_filter_changed)
        controls_layout.addWidget(self.location_filter)

        controls_layout.addStretch()

        # Set Location button
        self.set_location_btn = QPushButton("Set Location")
        self.set_location_btn.setToolTip("Set location for scans without a location")
        self.set_location_btn.clicked.connect(self._set_location)
        self.set_location_btn.setEnabled(False)
        controls_layout.addWidget(self.set_location_btn)

        controls_layout.addSpacing(10)

        # Sync button
        self.sync_btn = QPushButton("Sync")
        self.sync_btn.setToolTip("Sync scans with online database")
        self.sync_btn.clicked.connect(self._sync_scans)
        controls_layout.addWidget(self.sync_btn)

        controls_layout.addSpacing(20)

        self.delete_btn = QPushButton("Delete Selected")
        self.delete_btn.setProperty("class", "danger")
        self.delete_btn.clicked.connect(self._delete_selected)
        self.delete_btn.setEnabled(False)
        controls_layout.addWidget(self.delete_btn)

        self.clear_all_btn = QPushButton("Clear All")
        self.clear_all_btn.setProperty("class", "danger")
        self.clear_all_btn.clicked.connect(self._clear_all)
        controls_layout.addWidget(self.clear_all_btn)

        layout.addLayout(controls_layout)

        # Summary label
        self.summary_label = QLabel("Total scans: 0")
        self.summary_label.setProperty("class", "muted")
        layout.addWidget(self.summary_label)

        # Scans table
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "Scan Time", "Location", "Rank", "Contracted By", "Reward", "Availability", "Objectives", "ID"
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)  # Disable default editing
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)

        # Column widths
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)  # Scan Time
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)  # Location
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)  # Rank
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)  # Contracted By
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)  # Reward
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)  # Availability
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)           # Objectives
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)  # ID

        layout.addWidget(self.table, 1)  # Give table stretch priority

        # Details group with fixed height
        details_group = QGroupBox("Selected Scan Details")
        details_group.setFixedHeight(150)
        details_layout = QVBoxLayout()

        self.details_label = QLabel("Select a scan to view details")
        self.details_label.setWordWrap(True)
        details_layout.addWidget(self.details_label)

        details_group.setLayout(details_layout)
        layout.addWidget(details_group, 0)  # No stretch

    def _load_initial_data(self):
        """Load initial data from database on startup."""
        # Populate location filter
        self.location_filter.blockSignals(True)
        self.location_filter.clear()
        self.location_filter.addItem("All Locations")
        self.location_filter.addItem("No Location")

        locations = self.scan_db.get_locations_with_scans()
        for loc in locations:
            self.location_filter.addItem(loc)

        self.location_filter.blockSignals(False)

        # Load table
        self._refresh_table()

    def _update_location_filter(self, new_location: str = None):
        """Update location filter dropdown, optionally adding a new location."""
        if new_location and self.location_filter.findText(new_location) == -1:
            self.location_filter.addItem(new_location)

    def add_scan_to_table(self, scan: dict):
        """Add a single scan to the table (called when a new scan is captured)."""
        # Update location filter if needed
        scan_locations = scan.get("scan_locations", [])
        for loc in scan_locations:
            if loc:
                self._update_location_filter(loc)

        # Update summary
        total = len(self.scan_db.scans)
        filter_text = self.location_filter.currentText()
        if filter_text == "All Locations":
            self.summary_label.setText(f"Total scans: {total}")

        # Check if scan should be visible with current filter
        if filter_text == "All Locations":
            pass  # Always show
        elif filter_text == "No Location":
            if scan_locations:
                return  # Don't show - has locations
        elif filter_text not in scan_locations:
            return  # Don't show - filter location not in scan's locations

        # Add row to table
        self._add_scan_row(scan)

    def _reload_table(self):
        """Reload the entire table from database (used after delete)."""
        self._refresh_table()

    def _add_scan_row(self, scan: dict, insert_at_top: bool = True):
        """Add a single scan row to the table."""
        self.table.setSortingEnabled(False)

        if insert_at_top:
            row = 0
            self.table.insertRow(0)
        else:
            row = self.table.rowCount()
            self.table.insertRow(row)

        # Check if scan is unsynced (for highlighting)
        is_unsynced = not scan.get("synced", False)
        unsynced_brush = QBrush(UNSYNCED_BG_COLOR) if is_unsynced else None

        # Scan time
        scan_time = scan.get("scan_timestamp", "")
        try:
            dt = datetime.fromisoformat(scan_time)
            time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        except:
            time_str = scan_time
        time_item = QTableWidgetItem(time_str)
        time_item.setData(Qt.ItemDataRole.UserRole, scan.get("id"))
        # Store synced status for sorting (0 = unsynced, 1 = synced)
        time_item.setData(Qt.ItemDataRole.UserRole + 1, 0 if is_unsynced else 1)
        if unsynced_brush:
            time_item.setBackground(unsynced_brush)
        self.table.setItem(row, 0, time_item)

        # Location - now supports multiple locations
        locations = scan.get("scan_locations", [])
        if not locations:
            location_str = "(No Location)"
            loc_item = QTableWidgetItem(location_str)
            loc_item.setForeground(QColor("#ff9800"))
        elif len(locations) == 1:
            location_str = locations[0]
            loc_item = QTableWidgetItem(location_str)
        else:
            location_str = f"{locations[0]} (+{len(locations)-1} more)"
            loc_item = QTableWidgetItem(location_str)
            loc_item.setToolTip("\n".join(locations))
        if unsynced_brush:
            loc_item.setBackground(unsynced_brush)
        self.table.setItem(row, 1, loc_item)

        # Mission data
        mission_data = scan.get("mission_data", {})

        # Rank
        rank = mission_data.get("rank", "")
        rank_item = QTableWidgetItem(rank if rank else "-")
        if not rank:
            rank_item.setForeground(QColor("#808080"))
        if unsynced_brush:
            rank_item.setBackground(unsynced_brush)
        self.table.setItem(row, 2, rank_item)

        # Contracted By
        contracted_by = mission_data.get("contracted_by", "")
        contracted_item = QTableWidgetItem(contracted_by if contracted_by else "-")
        if not contracted_by:
            contracted_item.setForeground(QColor("#808080"))
        if unsynced_brush:
            contracted_item.setBackground(unsynced_brush)
        self.table.setItem(row, 3, contracted_item)

        # Reward
        reward = mission_data.get("reward", 0)
        reward_item = QTableWidgetItem(f"{reward:,.0f} aUEC")
        reward_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if unsynced_brush:
            reward_item.setBackground(unsynced_brush)
        self.table.setItem(row, 4, reward_item)

        # Availability
        avail = mission_data.get("availability", "")
        avail_item = QTableWidgetItem(avail)
        if unsynced_brush:
            avail_item.setBackground(unsynced_brush)
        self.table.setItem(row, 5, avail_item)

        # Objectives summary
        objectives = mission_data.get("objectives", [])
        if objectives:
            obj_summary = f"{len(objectives)} objective(s): "
            obj_parts = []
            for obj in objectives[:3]:  # Show first 3
                scu = obj.get("scu_amount", 0)
                dest = obj.get("deliver_to", "?")
                # Shorten destination
                if len(dest) > 30:
                    dest = dest[:27] + "..."
                obj_parts.append(f"{scu} SCU -> {dest}")
            obj_summary += "; ".join(obj_parts)
            if len(objectives) > 3:
                obj_summary += f" (+{len(objectives) - 3} more)"
        else:
            obj_summary = "No objectives"
        obj_item = QTableWidgetItem(obj_summary)
        if unsynced_brush:
            obj_item.setBackground(unsynced_brush)
        self.table.setItem(row, 6, obj_item)

        # ID (shortened)
        scan_id = scan.get("id", "")
        id_item = QTableWidgetItem(scan_id[:8] + "...")
        id_item.setToolTip(scan_id)
        if unsynced_brush:
            id_item.setBackground(unsynced_brush)
        self.table.setItem(row, 7, id_item)

        self.table.setSortingEnabled(True)

    def _refresh_table(self):
        """Refresh the scans table based on current filter."""
        # Get filter
        filter_text = self.location_filter.currentText()

        if filter_text == "No Location":
            # Show scans with no locations
            scans = [
                s for s in self.scan_db.get_scans()
                if not s.get("scan_locations", [])
            ]
        elif filter_text != "All Locations":
            # Filter by specific location
            scans = self.scan_db.get_scans(location=filter_text)
        else:
            scans = self.scan_db.get_scans()

        # Sort: unsynced first, then by timestamp (most recent first)
        scans.sort(key=lambda x: (
            x.get("synced", False),  # False (0) comes before True (1)
            x.get("scan_timestamp", "")
        ), reverse=False)
        # Reverse only timestamp within each group
        unsynced = [s for s in scans if not s.get("synced", False)]
        synced = [s for s in scans if s.get("synced", False)]
        unsynced.sort(key=lambda x: x.get("scan_timestamp", ""), reverse=True)
        synced.sort(key=lambda x: x.get("scan_timestamp", ""), reverse=True)
        scans = unsynced + synced

        # Update summary
        total = len(self.scan_db.scans)
        filtered = len(scans)
        unsynced_count = len(unsynced)
        if filter_text == "All Locations":
            if unsynced_count > 0:
                self.summary_label.setText(f"Total scans: {total} ({unsynced_count} unsynced)")
            else:
                self.summary_label.setText(f"Total scans: {total}")
        else:
            if unsynced_count > 0:
                self.summary_label.setText(f"Showing {filtered} of {total} scans ({unsynced_count} unsynced)")
            else:
                self.summary_label.setText(f"Showing {filtered} of {total} scans")

        # Populate table
        self.table.setRowCount(0)

        for scan in scans:
            self._add_scan_row(scan, insert_at_top=False)

        self._on_selection_changed()

    def _on_filter_changed(self):
        """Handle filter change."""
        self._refresh_table()

    def _on_cell_double_clicked(self, row: int, column: int):
        """Handle double-click on a cell - allow editing location for scans without one."""
        # Only handle double-click on Location column (column 1)
        if column != 1:
            return

        # Get the scan
        scan_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        scan = self.scan_db.get_scan(scan_id)
        if not scan:
            return

        # Only allow editing if scan has no location
        if scan.get("scan_location") is not None:
            return

        # Use the dialog-based location setter
        self._set_location_for_scan(scan_id)

    def _on_selection_changed(self):
        """Handle selection change in table."""
        selected_rows = self.table.selectionModel().selectedRows()
        self.delete_btn.setEnabled(len(selected_rows) > 0)
        self.set_location_btn.setEnabled(len(selected_rows) > 0)

        if len(selected_rows) == 1:
            row = selected_rows[0].row()
            scan_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            scan = self.scan_db.get_scan(scan_id)
            if scan:
                self._show_scan_details(scan)
            else:
                self.details_label.setText("Scan not found")
        elif len(selected_rows) > 1:
            self.details_label.setText(f"{len(selected_rows)} scans selected")
        else:
            self.details_label.setText("Select a scan to view details")

    def _show_scan_details(self, scan: dict):
        """Show detailed info for a scan."""
        mission_data = scan.get("mission_data", {})

        lines = []
        lines.append(f"Scan ID: {scan.get('id', 'N/A')}")
        lines.append(f"Scan Time: {scan.get('scan_timestamp', 'N/A')}")

        # Show locations (supports multiple)
        locations = scan.get("scan_locations", [])
        if not locations:
            lines.append("Location: (No Location)")
        elif len(locations) == 1:
            lines.append(f"Location: {locations[0]}")
        else:
            lines.append(f"Locations ({len(locations)}):")
            for loc in locations:
                lines.append(f"  - {loc}")
        lines.append("")
        rank = mission_data.get('rank', '')
        lines.append(f"Rank: {rank if rank else '(not detected)'}")
        contracted_by = mission_data.get('contracted_by', '')
        lines.append(f"Contracted By: {contracted_by if contracted_by else '(not detected)'}")
        lines.append(f"Reward: {mission_data.get('reward', 0):,.0f} aUEC")
        lines.append(f"Availability: {mission_data.get('availability', 'N/A')}")
        lines.append("")

        objectives = mission_data.get("objectives", [])
        lines.append(f"Objectives ({len(objectives)}):")
        for i, obj in enumerate(objectives, 1):
            lines.append(f"  {i}. Collect from: {obj.get('collect_from', 'N/A')}")
            lines.append(f"     Deliver to: {obj.get('deliver_to', 'N/A')}")
            lines.append(f"     Amount: {obj.get('scu_amount', 0)} SCU")
            cargo = obj.get('cargo_type', '')
            if cargo:
                lines.append(f"     Cargo: {cargo}")

        self.details_label.setText("\n".join(lines))

    def _set_location_for_scan(self, scan_id: str):
        """Set location for a single scan using dialog."""
        self._show_location_dialog([scan_id])

    def _set_location(self):
        """Set location for selected scans."""
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            return

        # Get IDs of all selected scans
        scan_ids = []
        for index in selected_rows:
            row = index.row()
            scan_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            scan_ids.append(scan_id)

        if not scan_ids:
            return

        self._show_location_dialog(scan_ids)

    def _show_location_dialog(self, scan_ids: List[str]):
        """Show dialog to set location for given scan IDs."""
        if not scan_ids:
            return

        # Get available locations
        locations = SPECIAL_LOCATIONS + self.location_matcher.get_scannable_locations()

        # Create dialog with line edit and autocomplete
        dialog = QDialog(self)
        dialog.setWindowTitle("Set Location")
        dialog.setMinimumWidth(350)

        layout = QVBoxLayout(dialog)

        label = QLabel(f"Set location for {len(scan_ids)} scan(s):")
        layout.addWidget(label)

        location_edit = QLineEdit()
        location_edit.setPlaceholderText("Type to search locations...")

        # Add completer for autocomplete
        completer = QCompleter(locations)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setMaxVisibleItems(15)
        location_edit.setCompleter(completer)

        layout.addWidget(location_edit)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_location = location_edit.text().strip()
            if not new_location:
                QMessageBox.warning(self, "No Location", "Please enter a location.")
                return

            # Update all selected scans
            updated = 0
            for scan_id in scan_ids:
                if self.scan_db.update_scan_location(scan_id, new_location):
                    updated += 1

            if updated > 0:
                logger.info(f"Updated location for {updated} scan(s) to: {new_location}")
                self._load_initial_data()

    def _delete_selected(self):
        """Delete selected scans."""
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            return

        count = len(selected_rows)
        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Delete {count} selected scan(s)?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            # Get IDs to delete
            ids_to_delete = []
            for index in selected_rows:
                row = index.row()
                scan_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
                ids_to_delete.append(scan_id)

            # Delete scans
            deleted = 0
            for scan_id in ids_to_delete:
                if self.scan_db.delete_scan(scan_id):
                    deleted += 1

            logger.info(f"Deleted {deleted} scan(s)")
            self._load_initial_data()

    def _clear_all(self):
        """Clear all scans from the database."""
        count = len(self.scan_db.scans)
        if count == 0:
            QMessageBox.information(self, "Empty", "The scan database is already empty.")
            return

        reply = QMessageBox.question(
            self,
            "Confirm Clear All",
            f"Delete ALL {count} scans from the database?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            # Delete all scans
            for scan in self.scan_db.scans.copy():
                self.scan_db.delete_scan(scan["id"])

            logger.info(f"Cleared all {count} scans from database")
            self._load_initial_data()

    def _sync_scans(self):
        """Sync scans with online database."""
        if not self.sync_service:
            QMessageBox.warning(
                self,
                "Sync Not Available",
                "Sync service not initialized."
            )
            return

        if not self.sync_service.is_configured():
            QMessageBox.warning(
                self,
                "Sync Not Configured",
                "Please configure the Sync API URL in the Configuration tab.\n\n"
                "You need to deploy the Cloudflare Worker first.\n"
                "See cloudflare-worker/README.md for instructions."
            )
            return

        # Check if authenticated with Discord
        if not self.sync_service.is_authenticated():
            reply = QMessageBox.question(
                self,
                "Login Required",
                "You need to login with Discord to sync missions.\n\n"
                "Would you like to login now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.login_requested.emit()
            return

        # Test connection first
        self.sync_btn.setEnabled(False)
        self.sync_btn.setText("Connecting...")
        QApplication.processEvents()

        test_result = self.sync_service.test_connection()
        if not test_result.get("success"):
            self.sync_btn.setEnabled(True)
            self.sync_btn.setText("Sync")
            QMessageBox.critical(
                self,
                "Connection Failed",
                f"Could not connect to sync server:\n\n{test_result.get('error', 'Unknown error')}"
            )
            return

        # Get local scans
        local_scans = self.scan_db.get_scans()

        # Show progress
        self.sync_btn.setText("Syncing...")
        QApplication.processEvents()

        # Perform sync
        result = self.sync_service.sync(local_scans)

        self.sync_btn.setEnabled(True)
        self.sync_btn.setText("Sync")

        if result.get("success"):
            uploaded = result.get("uploaded", 0)
            updated = result.get("updated", 0)
            duplicates = result.get("duplicates", 0)
            downloaded = result.get("downloaded", [])

            # Mark all local scans as synced (they were either uploaded or already on server)
            for scan in self.scan_db.scans:
                if not scan.get("synced", False):
                    scan["synced"] = True

            # Import downloaded scans
            imported = 0
            for scan in downloaded:
                # Check if we already have this scan
                if not self.scan_db.get_scan(scan["id"]):
                    # Handle both scan_locations (array) and legacy scan_location (string)
                    locations = scan.get("scan_locations", [])
                    if not locations and scan.get("scan_location"):
                        locations = [scan.get("scan_location")]

                    # Add to local database (already synced since it came from server)
                    self.scan_db.scans.append({
                        "id": scan["id"],
                        "scan_timestamp": scan.get("scan_timestamp"),
                        "scan_locations": locations,
                        "mission_data": scan.get("mission_data", {}),
                        "synced_from": scan.get("uploaded_by", "unknown"),
                        "synced": True
                    })
                    imported += 1

            # Save changes (synced flags and imported scans)
            self.scan_db.save()
            self._load_initial_data()

            # Show summary
            username = self.sync_service.get_username() or "Unknown"
            summary = f"Sync complete! (as {username})\n\n"
            summary += f"Uploaded: {uploaded} new scans\n"
            if updated > 0:
                summary += f"Updated: {updated} scan locations\n"
            summary += f"Skipped: {duplicates} duplicates\n"
            summary += f"Downloaded: {imported} new scans from others"

            QMessageBox.information(self, "Sync Complete", summary)
            logger.info(f"Sync complete: uploaded {uploaded}, updated {updated}, downloaded {imported}")

        else:
            QMessageBox.critical(
                self,
                "Sync Failed",
                f"Sync failed:\n\n{result.get('error', 'Unknown error')}"
            )

    def set_discord_auth(self, discord_auth: "DiscordAuth"):
        """Set the Discord auth instance and update sync service."""
        self.discord_auth = discord_auth
        if self.sync_service:
            self.sync_service.discord_auth = discord_auth
