"""
Route Planner tab for PyQt6.

Intelligent cargo loading and route optimization with interactive stop tracking.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QComboBox, QGroupBox, QMessageBox, QTreeWidget,
    QTreeWidgetItem, QMenu, QHeaderView, QStyledItemDelegate
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QBrush, QAction, QPainter

from src.config import Config
from src.mission_manager import MissionManager
from src.route_optimizer import RouteOptimizer
from src.logger import get_logger

logger = get_logger()


class ColoredItemDelegate(QStyledItemDelegate):
    """Custom delegate to paint item backgrounds with custom colors."""

    def paint(self, painter, option, index):
        """Paint item with custom background color if set."""
        # Get custom background color from item data
        bg_color = index.data(Qt.ItemDataRole.BackgroundRole)

        if bg_color and isinstance(bg_color, (QColor, QBrush)):
            # Extract QColor from QBrush if needed
            if isinstance(bg_color, QBrush):
                bg_color = bg_color.color()

            # Fill background with custom color
            painter.fillRect(option.rect, bg_color)

        # Call parent to paint the rest (text, etc.)
        super().paint(painter, option, index)


class RoutePlannerTab(QWidget):
    """Route planning and cargo loading optimization tab with interactive tracking."""

    def __init__(self, config: Config, mission_manager: MissionManager):
        super().__init__()

        self.config = config
        self.mission_manager = mission_manager

        # Load ship profiles if available
        try:
            from src.ship_profiles import ShipManager
            self.ship_manager = ShipManager()
            self.has_ship_profiles = True
        except ImportError:
            self.ship_manager = None
            self.has_ship_profiles = False
            logger.warning("Ship profiles not available")

        # State
        self.selected_ship_capacity = config.get("route_planner", "ship_capacity", default=96)
        self.optimization_level = config.get("route_planner", "optimization_level", default="medium")
        self.current_route = None
        self.completed_stops = set()  # Track completed stop numbers
        self.completed_missions = set()  # Track completed mission IDs
        self.completed_deliveries = set()  # Track completed deliveries as (mission_id, deliver_to) tuples

        self._setup_ui()

    def _setup_ui(self):
        """Setup the route planner UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Compact toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        # Ship info display (read-only, configured in Settings)
        ship_name = self.config.get("route_planner", "selected_ship", default="ARGO_RAFT")
        self.ship_label = QLabel(f"Ship: {ship_name} ({self.selected_ship_capacity} SCU)")
        self.ship_label.setProperty("class", "muted")
        toolbar.addWidget(self.ship_label)

        toolbar.addWidget(QLabel("|"))

        # Status label in toolbar
        self.status_label = QLabel()
        self.status_label.setProperty("class", "muted")
        toolbar.addWidget(self.status_label)

        toolbar.addStretch()

        # Action buttons
        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.setProperty("class", "secondary")
        refresh_btn.clicked.connect(self.refresh)
        toolbar.addWidget(refresh_btn)

        optimize_btn = QPushButton("⚡ Optimize")
        optimize_btn.clicked.connect(self.refresh)
        toolbar.addWidget(optimize_btn)

        reset_btn = QPushButton("🔁 Reset")
        reset_btn.setProperty("class", "secondary")
        reset_btn.clicked.connect(self._reset_progress)
        toolbar.addWidget(reset_btn)

        layout.addLayout(toolbar)

        # Route tree
        route_group = QGroupBox("Route Plan (Double-click to complete)")
        route_layout = QVBoxLayout()
        route_layout.setContentsMargins(4, 4, 4, 4)
        route_layout.setSpacing(4)

        self.route_tree = QTreeWidget()
        self.route_tree.setColumnCount(5)
        self.route_tree.setHeaderLabels(["#", "Status", "Location", "Actions", "Cargo"])
        self.route_tree.setAlternatingRowColors(False)  # Disabled to allow custom background colors

        # Install custom delegate to force background colors to render
        self.route_tree.setItemDelegate(ColoredItemDelegate(self.route_tree))

        # Override stylesheet to allow custom item backgrounds
        self.route_tree.setStyleSheet("""
            QTreeWidget {
                background-color: #2d2d2d;
                color: #e0e0e0;
                border: 1px solid #3d3d3d;
                border-radius: 4px;
                outline: none;
            }
            QTreeWidget::item {
                padding: 6px 4px;
                border: none;
            }
            QTreeWidget::item:selected {
                background-color: #0078d4;
                color: #ffffff;
            }
        """)

        self.route_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.route_tree.customContextMenuRequested.connect(self._show_context_menu)
        self.route_tree.itemDoubleClicked.connect(self._toggle_stop_completion)

        # Column widths - optimize for cargo (small), location and actions (larger)
        header = self.route_tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)  # #
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)  # Status
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)       # Location (more space)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)           # Actions (takes remaining)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)       # Cargo (compact)

        # Set column widths
        self.route_tree.setColumnWidth(2, 240)  # Location - increased from 180
        self.route_tree.setColumnWidth(4, 110)  # Cargo - compact fixed width

        route_layout.addWidget(self.route_tree)
        route_group.setLayout(route_layout)
        layout.addWidget(route_group)

    def refresh(self):
        """Refresh and optimize route."""
        missions = self.mission_manager.get_missions(status="active")

        if not missions:
            self.route_tree.clear()
            self.status_label.setText("No missions to plan")
            return

        try:
            # Get algorithm from config
            algorithm = self.config.get("route_planner", "algorithm", default="VRP Solver")

            # Generate optimized route based on selected algorithm
            if algorithm == "Dynamic (Regret-2 + ALNS)":
                try:
                    # Use dynamic VRP solver
                    from src.services.dynamic_vrp_solver import DynamicVRPSolver
                    from src.domain.models import Mission, Objective

                    # Convert mission dicts to Mission objects
                    # Need to properly convert objectives from dicts to Objective objects
                    mission_objects = []
                    for m in missions:
                        # Convert objective dicts to Objective objects
                        objectives = [Objective.from_dict(obj) if isinstance(obj, dict) else obj
                                     for obj in m.get('objectives', [])]

                        # Create Mission with converted objectives
                        mission_obj = Mission(
                            reward=m['reward'],
                            availability=m.get('availability', 'N/A'),
                            objectives=objectives,
                            id=m.get('id'),
                            timestamp=m.get('timestamp'),
                            status=m.get('status', 'active')
                        )
                        mission_objects.append(mission_obj)

                    # Use advanced optimization level for dynamic solver
                    solver = DynamicVRPSolver(
                        ship_capacity=self.selected_ship_capacity,
                        starting_location=None
                    )

                    # Set optimization level (use selected level)
                    opt_level = self.optimization_level
                    self.current_route = solver.solve(
                        missions=mission_objects,
                        optimization_level=opt_level,
                        time_budget_ms=3000  # 3 seconds for optimization
                    )

                    self.status_label.setText(f"Optimized using {algorithm}")

                except Exception as solver_error:
                    logger.error(f"Dynamic solver failed: {solver_error}", exc_info=True)
                    logger.info("Falling back to standard VRP solver")

                    # Fallback to standard VRP solver
                    self.current_route = RouteOptimizer.create_vrp_route(
                        missions,
                        ship_capacity=self.selected_ship_capacity,
                        starting_location=None,
                        optimization_level=self.optimization_level
                    )

                    self.status_label.setText(f"Using VRP Solver (Dynamic solver failed)")
                    QMessageBox.warning(
                        self,
                        "Solver Fallback",
                        f"Dynamic solver encountered an error. Falling back to standard VRP solver.\n\nError: {str(solver_error)}"
                    )
            else:
                # Use existing VRP solver
                self.current_route = RouteOptimizer.create_vrp_route(
                    missions,
                    ship_capacity=self.selected_ship_capacity,
                    starting_location=None,
                    optimization_level=self.optimization_level
                )

                self.status_label.setText(f"Optimized using VRP Solver")

            # Update display
            self._update_route_display()

            logger.info(f"Route optimized with {algorithm}: {len(self.current_route.stops)} stops")

        except Exception as e:
            logger.error(f"Route optimization failed: {e}", exc_info=True)

            # Clear display on complete failure
            self.route_tree.clear()
            self.status_label.setText("Optimization failed")

            QMessageBox.critical(
                self,
                "Optimization Error",
                f"Failed to optimize route:\n{str(e)}\n\nThe application will continue running."
            )

    def _find_delivery_stop_number(self, destination: str, current_stop: int) -> int:
        """
        Find which stop number a destination will be visited for delivery.

        Args:
            destination: The delivery location name
            current_stop: Current stop number (to search after this)

        Returns:
            Stop number where delivery occurs, or 0 if not found
        """
        if not self.current_route:
            return 0

        # Search stops after current stop
        for i, stop in enumerate(self.current_route.stops[current_stop:], current_stop + 1):
            if stop.location == destination:
                return i

        return 0

    def _sort_pickups_by_delivery_order(self, pickups, current_stop_num: int):
        """
        Sort pickups by their delivery order in the route using LIFO (Last In, First Out).
        Items delivered LAST are listed first (load deep in cargo hold).
        Items delivered FIRST are listed last (load near entrance, accessible).

        Args:
            pickups: List of Objective pickups at this stop
            current_stop_num: Current stop number in route

        Returns:
            Sorted list of pickups in LIFO order (latest delivery first)
        """
        # Create list with delivery stop numbers
        pickup_with_stops = []
        for pickup in pickups:
            delivery_stop = self._find_delivery_stop_number(pickup.deliver_to, current_stop_num)
            pickup_with_stops.append((pickup, delivery_stop))

        # Sort by: 1) delivery stop number DESCENDING (LIFO), 2) destination name, 3) SCU amount
        pickup_with_stops.sort(key=lambda x: (
            -x[1] if x[1] > 0 else -999,  # Reverse order: later deliveries first, unknown go first
            x[0].deliver_to,  # Group by destination
            -x[0].scu_amount  # Within same destination, larger items first
        ))

        return [pickup for pickup, _ in pickup_with_stops]

    def _get_destination_color(self, destination: str, destination_colors: dict) -> QColor:
        """
        Get a distinct color for a destination.

        Args:
            destination: Destination location name
            destination_colors: Dictionary tracking destination to color index mapping

        Returns:
            QColor for the destination
        """
        # Palette of subtle, muted colors for dark theme (grey-ish but distinct)
        color_palette = [
            QColor(70, 50, 50),     # Muted dark red
            QColor(50, 55, 70),     # Muted dark blue
            QColor(50, 65, 50),     # Muted dark green
            QColor(70, 60, 50),     # Muted dark orange/brown
            QColor(60, 50, 70),     # Muted dark purple
            QColor(70, 50, 60),     # Muted dark pink
            QColor(50, 65, 65),     # Muted dark cyan
            QColor(65, 65, 50),     # Muted dark olive
            QColor(60, 60, 60),     # Medium gray
        ]

        # Assign color index to new destinations
        if destination not in destination_colors:
            destination_colors[destination] = len(destination_colors) % len(color_palette)

        return color_palette[destination_colors[destination]]

    def _update_route_display(self):
        """Update the route tree display."""
        self.route_tree.clear()

        if not self.current_route:
            return

        current_cargo = 0
        total_reward = 0

        for i, stop in enumerate(self.current_route.stops, 1):
            # Create stop item
            stop_item = QTreeWidgetItem(self.route_tree)
            stop_item.setData(0, Qt.ItemDataRole.UserRole, i)  # Store stop number

            # Stop number
            stop_item.setText(0, str(i))

            # Status
            is_complete = i in self.completed_stops
            status = "✅ Complete" if is_complete else "⏳ Pending"
            stop_item.setText(1, status)

            # Location
            stop_item.setText(2, stop.location)

            # Actions summary
            actions = []
            if stop.pickups:
                pickup_scu = sum(p.scu_amount for p in stop.pickups)
                actions.append(f"📦 LOAD {pickup_scu} SCU")
            if stop.deliveries:
                delivery_scu = sum(d.scu_amount for d in stop.deliveries)
                actions.append(f"📤 DELIVER {delivery_scu} SCU")
            stop_item.setText(3, " | ".join(actions))

            # Update cargo tracking
            for pickup in stop.pickups:
                current_cargo += pickup.scu_amount
            for delivery in stop.deliveries:
                current_cargo -= delivery.scu_amount
                total_reward += delivery.reward if hasattr(delivery, 'reward') else 0

            # Cargo load percentage
            cargo_pct = (current_cargo / self.selected_ship_capacity * 100) if self.selected_ship_capacity > 0 else 0
            stop_item.setText(4, f"{current_cargo} SCU ({cargo_pct:.0f}%)")

            # Color code completed stops
            if is_complete:
                for col in range(5):
                    stop_item.setForeground(col, QBrush(QColor("#4caf50")))

            # Add detail rows for pickups - grouped by destination and sorted by delivery order
            if stop.pickups:
                sorted_pickups = self._sort_pickups_by_delivery_order(stop.pickups, i)

                # Track destination colors for this stop
                destination_colors = {}

                for pickup in sorted_pickups:
                    detail_item = QTreeWidgetItem(stop_item)

                    # Find delivery stop number for this pickup
                    delivery_stop_num = self._find_delivery_stop_number(pickup.deliver_to, i)
                    stop_indicator = f" (Stop #{delivery_stop_num})" if delivery_stop_num else ""

                    detail_item.setText(2, f"  📦 Load: {pickup.scu_amount} SCU {pickup.cargo_type}")
                    detail_item.setText(3, f"→ Deliver to {pickup.deliver_to}{stop_indicator}")

                    # Apply colored background for destination grouping
                    bg_color = self._get_destination_color(pickup.deliver_to, destination_colors)
                    for col in range(5):
                        detail_item.setData(col, Qt.ItemDataRole.BackgroundRole, bg_color)

                    if is_complete:
                        for col in range(5):
                            detail_item.setForeground(col, QBrush(QColor("#808080")))

            # Add detail rows for deliveries
            for delivery in stop.deliveries:
                detail_item = QTreeWidgetItem(stop_item)
                detail_item.setText(2, f"  📤 Deliver: {delivery.scu_amount} SCU {delivery.cargo_type}")
                detail_item.setText(3, f"← From {delivery.collect_from}")
                if is_complete:
                    for col in range(5):
                        detail_item.setForeground(col, QBrush(QColor("#808080")))

            # Auto-collapse completed stops, keep pending stops expanded
            stop_item.setExpanded(not is_complete)

        # Update status
        completed = len(self.completed_stops)
        total = len(self.current_route.stops)
        self.status_label.setText(
            f"Progress: {completed}/{total} stops  |  {len(self.completed_missions)} missions done"
        )

    def _toggle_stop_completion(self, item: QTreeWidgetItem, column: int):
        """Toggle stop completion on double-click."""
        stop_num = item.data(0, Qt.ItemDataRole.UserRole)
        if not stop_num:
            return  # Detail row clicked

        if stop_num in self.completed_stops:
            self.completed_stops.remove(stop_num)
        else:
            self._complete_stop_and_missions(stop_num)

        self._update_route_display()

    def _complete_stop_and_missions(self, stop_num: int):
        """Mark stop complete and complete associated missions."""
        self.completed_stops.add(stop_num)

        # Find missions at this stop and check if they're fully completed
        if self.current_route and stop_num <= len(self.current_route.stops):
            stop = self.current_route.stops[stop_num - 1]

            # Track which deliveries were completed at this stop
            missions_with_deliveries = {}  # mission_id -> set of delivery locations

            for delivery in stop.deliveries:
                if hasattr(delivery, 'mission_id') and delivery.mission_id:
                    mission_id = delivery.mission_id
                    deliver_to = delivery.deliver_to

                    # Track this completed delivery
                    self.completed_deliveries.add((mission_id, deliver_to))

                    # Group deliveries by mission for checking completion
                    if mission_id not in missions_with_deliveries:
                        missions_with_deliveries[mission_id] = set()
                    missions_with_deliveries[mission_id].add(deliver_to)

            # For each mission that had deliveries at this stop, check if ALL objectives are complete
            for mission_id in missions_with_deliveries:
                if mission_id not in self.completed_missions:
                    # Get the full mission data to check all objectives
                    missions = self.mission_manager.get_missions()
                    mission = next((m for m in missions if m.get("id") == mission_id), None)

                    if mission:
                        # Check if ALL delivery objectives of this mission are completed
                        all_objectives = mission.get("objectives", [])
                        all_completed = True

                        for obj in all_objectives:
                            obj_deliver_to = obj.get("deliver_to", "")
                            # Check if this specific delivery has been completed
                            if (mission_id, obj_deliver_to) not in self.completed_deliveries:
                                all_completed = False
                                break

                        # Only mark mission as complete if ALL objectives are done
                        if all_completed:
                            self.completed_missions.add(mission_id)
                            self.mission_manager.update_status(mission_id, "completed")
                            logger.info(f"Marked mission {mission_id} as completed (all {len(all_objectives)} objectives delivered)")
                        else:
                            logger.debug(f"Mission {mission_id} not yet complete (partial deliveries done)")

    def _show_context_menu(self, position):
        """Show context menu for route stops."""
        item = self.route_tree.itemAt(position)
        if not item:
            return

        stop_num = item.data(0, Qt.ItemDataRole.UserRole)
        if not stop_num:
            return  # Detail row

        menu = QMenu(self)

        if stop_num in self.completed_stops:
            action = QAction("❌ Mark Incomplete", self)
            action.triggered.connect(lambda: self._mark_incomplete(stop_num))
        else:
            action = QAction("✅ Mark Complete", self)
            action.triggered.connect(lambda: self._mark_complete(stop_num))

        menu.addAction(action)
        menu.exec(self.route_tree.viewport().mapToGlobal(position))

    def _mark_complete(self, stop_num: int):
        """Mark stop as complete."""
        self._complete_stop_and_missions(stop_num)
        self._update_route_display()

    def _mark_incomplete(self, stop_num: int):
        """Mark stop as incomplete (visual only)."""
        if stop_num in self.completed_stops:
            self.completed_stops.remove(stop_num)
        self._update_route_display()

    def _reset_progress(self):
        """Reset all progress tracking."""
        reply = QMessageBox.question(
            self,
            "Reset Progress",
            "Reset all stop completion tracking?\n\n"
            "Note: This won't undo mission completions in the Hauling tab.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.completed_stops.clear()
            self.completed_deliveries.clear()
            self._update_route_display()
            logger.info("Progress tracking reset")

    def reload_config(self):
        """Reload configuration (called when config is saved in Settings tab)."""
        self.selected_ship_capacity = self.config.get("route_planner", "ship_capacity", default=96)
        self.optimization_level = self.config.get("route_planner", "optimization_level", default="medium")

        # Update ship display
        ship_name = self.config.get("route_planner", "selected_ship", default="ARGO_RAFT")
        self.ship_label.setText(f"Ship: {ship_name} ({self.selected_ship_capacity} SCU)")

        logger.debug(f"Route planner config reloaded: {ship_name} ({self.selected_ship_capacity} SCU)")
