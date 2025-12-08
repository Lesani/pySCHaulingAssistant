"""
Route Planner tab for PyQt6.

Intelligent cargo loading and route optimization with interactive stop tracking.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QComboBox, QGroupBox, QMessageBox, QTreeWidget,
    QTreeWidgetItem, QMenu, QHeaderView, QStyledItemDelegate
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QBrush, QAction, QPainter

from src.config import Config
from src.mission_manager import MissionManager
from src.route_optimizer import RouteOptimizer
from src.logger import get_logger

logger = get_logger()


class RouteOptimizerWorker(QThread):
    """Background worker for route optimization."""

    finished = pyqtSignal(object, str)  # (route, status_message)
    error = pyqtSignal(str, str)  # (error_message, fallback_status)

    def __init__(self, missions, ship_capacity, quality):
        super().__init__()
        self.missions = missions
        self.ship_capacity = ship_capacity
        self.quality = quality.lower()

    def run(self):
        """Run optimization in background thread."""
        try:
            # Filter out objectives that have already been picked up
            # These are "in cargo hold" and don't need pickup stops
            filtered_missions = []
            for m in self.missions:
                incomplete_objectives = [
                    obj for obj in m.get('objectives', [])
                    if not obj.get('pickup_completed', False)
                ]
                if incomplete_objectives:
                    filtered_mission = m.copy()
                    filtered_mission['objectives'] = incomplete_objectives
                    filtered_missions.append(filtered_mission)

            if self.quality == "fast":
                # Fast: VRP Solver with medium optimization (~200ms)
                route = RouteOptimizer.create_vrp_route(
                    filtered_missions,
                    ship_capacity=self.ship_capacity,
                    starting_location=None,
                    optimization_level="medium"
                )
                self.finished.emit(route, "Optimized (Fast)")

            elif self.quality in ("balanced", "best"):
                # Balanced/Best: Dynamic solver
                try:
                    from src.services.dynamic_vrp_solver import DynamicVRPSolver
                    from src.domain.models import Mission, Objective

                    # Convert filtered mission dicts to Mission objects
                    mission_objects = []
                    for m in filtered_missions:
                        objectives = [Objective.from_dict(obj) if isinstance(obj, dict) else obj
                                     for obj in m.get('objectives', [])]
                        mission_obj = Mission(
                            reward=m['reward'],
                            availability=m.get('availability', 'N/A'),
                            objectives=objectives,
                            id=m.get('id'),
                            timestamp=m.get('timestamp'),
                            status=m.get('status', 'active')
                        )
                        mission_objects.append(mission_obj)

                    solver = DynamicVRPSolver(
                        ship_capacity=self.ship_capacity,
                        starting_location=None
                    )

                    # Balanced = medium optimization (~500ms), Best = advanced (~3s)
                    opt_level = "medium" if self.quality == "balanced" else "advanced"
                    time_budget = 500 if self.quality == "balanced" else 3000

                    route = solver.solve(
                        missions=mission_objects,
                        optimization_level=opt_level,
                        time_budget_ms=time_budget
                    )
                    self.finished.emit(route, f"Optimized ({self.quality.capitalize()})")

                except Exception as solver_error:
                    logger.error(f"Dynamic solver failed: {solver_error}", exc_info=True)
                    # Fallback to VRP solver
                    route = RouteOptimizer.create_vrp_route(
                        filtered_missions,
                        ship_capacity=self.ship_capacity,
                        starting_location=None,
                        optimization_level="advanced"
                    )
                    self.error.emit(str(solver_error), "Optimized (VRP fallback)")
                    self.finished.emit(route, "Optimized (VRP fallback)")

            else:
                # Unknown quality, default to VRP medium
                route = RouteOptimizer.create_vrp_route(
                    filtered_missions,
                    ship_capacity=self.ship_capacity,
                    starting_location=None,
                    optimization_level="medium"
                )
                self.finished.emit(route, "Optimized")

        except Exception as e:
            logger.error(f"Route optimization failed: {e}", exc_info=True)
            self.error.emit(str(e), "")


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
        self.route_quality = config.get("route_planner", "route_quality", default="best")
        self.current_route = None
        self._optimization_generation = 0  # Counter to ignore stale results
        self._active_workers = []  # Keep references to prevent garbage collection

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
        """Refresh and optimize route in background thread."""
        missions = self.mission_manager.get_missions(status="active")

        if not missions:
            self.route_tree.clear()
            self.status_label.setText("No missions to plan")
            return

        # Increment generation to ignore results from any previous workers
        self._optimization_generation += 1
        current_generation = self._optimization_generation

        # Show optimizing status
        self.status_label.setText("Optimizing...")

        # Calculate available capacity (ship capacity minus cargo already in hold)
        cargo_in_hold = self._get_cargo_in_hold()
        cargo_in_hold_scu = sum(obj.get("scu_amount", 0) for obj in cargo_in_hold)
        available_capacity = max(0, self.selected_ship_capacity - cargo_in_hold_scu)

        # Start background optimization
        worker = RouteOptimizerWorker(
            missions=missions,
            ship_capacity=available_capacity,
            quality=self.route_quality
        )

        # Keep reference to prevent garbage collection
        self._active_workers.append(worker)

        # Use lambdas to capture current generation
        worker.finished.connect(
            lambda route, msg, gen=current_generation: self._on_optimization_finished(route, msg, gen)
        )
        worker.error.connect(
            lambda err, status, gen=current_generation: self._on_optimization_error(err, status, gen)
        )

        # Clean up worker when done
        worker.finished.connect(lambda: self._cleanup_worker(worker))

        worker.start()

    def _cleanup_worker(self, worker):
        """Remove finished worker from active list."""
        if worker in self._active_workers:
            self._active_workers.remove(worker)
        worker.deleteLater()

    def _on_optimization_finished(self, route, status_message, generation):
        """Handle optimization completion."""
        # Ignore stale results from old workers
        if generation != self._optimization_generation:
            return

        # Merge in-hold cargo deliveries into the route
        merged_route = self._merge_inhold_deliveries(route)
        # Filter out completed deliveries
        self.current_route = self._filter_route_for_display(merged_route)
        self.status_label.setText(status_message)
        self._update_route_display()
        logger.info(f"Route optimized: {len(self.current_route.stops)} stops - {status_message}")

    def _merge_inhold_deliveries(self, route):
        """
        Add deliveries for cargo in hold to the appropriate stops.

        Cargo in hold = objectives where pickup_completed=True but delivery_completed=False.
        These need delivery stops but not pickup stops.
        """
        cargo_in_hold = self._get_cargo_in_hold()
        if not cargo_in_hold:
            return route

        from src.domain.models import Objective

        # Group in-hold cargo by delivery destination
        by_destination = {}
        for obj_dict in cargo_in_hold:
            dest = obj_dict.get('deliver_to', '')
            if dest not in by_destination:
                by_destination[dest] = []
            # Convert dict to Objective for consistency
            obj = Objective(
                collect_from=obj_dict.get('collect_from', ''),
                deliver_to=dest,
                scu_amount=obj_dict.get('scu_amount', 0),
                cargo_type=obj_dict.get('cargo_type', 'Unknown'),
                mission_id=obj_dict.get('mission_id')
            )
            by_destination[dest].append(obj)

        # Add deliveries to existing stops or create new stops
        from src.domain.models import Stop, Route

        new_stops = list(route.stops)

        for dest, deliveries in by_destination.items():
            # Find existing stop at this destination
            found = False
            for stop in new_stops:
                if stop.location == dest:
                    # Add deliveries to existing stop
                    stop.deliveries.extend(deliveries)
                    found = True
                    break

            if not found:
                # Create new stop for these deliveries
                new_stop = Stop(
                    location=dest,
                    stop_number=len(new_stops) + 1,
                    pickups=[],
                    deliveries=deliveries,
                    cargo_before=0,
                    cargo_after=0
                )
                new_stops.append(new_stop)

        # Renumber stops
        for i, stop in enumerate(new_stops):
            stop.stop_number = i + 1

        return Route(stops=new_stops)

    def _filter_route_for_display(self, route):
        """
        Filter route to only show stops with pending actions.

        Removes:
        - Deliveries that are already completed (delivery_completed=True)
        - Stops that have no remaining actions after filtering
        """
        if not route:
            return route

        from src.domain.models import Stop, Route

        filtered_stops = []
        stop_number = 1

        for stop in route.stops:
            # Filter out completed deliveries
            pending_deliveries = []
            for delivery in stop.deliveries:
                if hasattr(delivery, 'mission_id') and delivery.mission_id:
                    _, delivery_done = self.mission_manager.get_objective_completion(
                        delivery.mission_id, delivery.collect_from, delivery.deliver_to
                    )
                    if not delivery_done:
                        pending_deliveries.append(delivery)
                else:
                    # No mission_id means we can't check completion, keep it
                    pending_deliveries.append(delivery)

            # Keep stop if it has any pending actions (pickups or pending deliveries)
            if stop.pickups or pending_deliveries:
                new_stop = Stop(
                    location=stop.location,
                    stop_number=stop_number,
                    pickups=stop.pickups,
                    deliveries=pending_deliveries,
                    cargo_before=stop.cargo_before,
                    cargo_after=stop.cargo_after
                )
                filtered_stops.append(new_stop)
                stop_number += 1

        return Route(stops=filtered_stops)

    def _get_cargo_in_hold(self):
        """
        Get objectives that are picked up but not yet delivered (in cargo hold).

        Returns objectives where:
        - pickup_completed = True (we have the cargo)
        - delivery_completed = False (we haven't delivered it yet)
        """
        in_hold = []
        for mission in self.mission_manager.get_missions(status="active"):
            for obj in mission.get("objectives", []):
                if obj.get("pickup_completed") and not obj.get("delivery_completed"):
                    in_hold.append(obj)
        return in_hold

    def _on_optimization_error(self, error_message, fallback_status, generation):
        """Handle optimization error."""
        # Ignore stale errors from old workers
        if generation != self._optimization_generation:
            return

        if not fallback_status:
            # Complete failure, no fallback
            self.route_tree.clear()
            self.status_label.setText("Optimization failed")
            QMessageBox.critical(
                self,
                "Optimization Error",
                f"Failed to optimize route:\n{error_message}\n\nThe application will continue running."
            )
        else:
            # Fallback was used, just warn
            QMessageBox.warning(
                self,
                "Solver Fallback",
                f"Dynamic solver failed. Using VRP solver.\n\nError: {error_message}"
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

    def _get_mission_color(self, mission_id: str, mission_colors: dict) -> QColor:
        """
        Get a distinct color for a mission.

        Args:
            mission_id: Mission UUID
            mission_colors: Dictionary tracking mission_id to color index mapping

        Returns:
            QColor for the mission
        """
        # Palette of distinct colors for missions (brighter than destination colors)
        color_palette = [
            QColor(60, 80, 60),     # Green tint
            QColor(60, 60, 80),     # Blue tint
            QColor(80, 70, 50),     # Orange/brown tint
            QColor(70, 50, 70),     # Purple tint
            QColor(50, 70, 70),     # Cyan tint
            QColor(80, 60, 60),     # Red tint
            QColor(70, 70, 50),     # Olive tint
            QColor(60, 70, 80),     # Steel blue tint
        ]

        # Assign color index to new missions
        if mission_id not in mission_colors:
            mission_colors[mission_id] = len(mission_colors) % len(color_palette)

        return color_palette[mission_colors[mission_id]]

    def _update_route_display(self):
        """Update the route tree display."""
        self.route_tree.clear()

        # Get cargo in hold (picked up but not delivered)
        cargo_in_hold = self._get_cargo_in_hold()
        current_cargo = sum(obj.get('scu_amount', 0) for obj in cargo_in_hold)

        # Show "In Cargo Hold" section if there's cargo
        if cargo_in_hold:
            hold_item = QTreeWidgetItem(self.route_tree)
            hold_item.setText(0, "")
            hold_item.setText(1, "[HOLD]")
            hold_item.setText(2, "Cargo Hold")
            hold_total_scu = sum(obj.get('scu_amount', 0) for obj in cargo_in_hold)
            hold_item.setText(3, f"{len(cargo_in_hold)} items loaded")
            cargo_pct = (hold_total_scu / self.selected_ship_capacity * 100) if self.selected_ship_capacity > 0 else 0
            hold_item.setText(4, f"{hold_total_scu} SCU ({cargo_pct:.0f}%)")

            # Style the hold section header
            for col in range(5):
                hold_item.setForeground(col, QBrush(QColor("#4caf50")))  # Green

            # Add detail rows for cargo in hold, colored by mission
            mission_colors = {}  # Track colors per mission_id
            for obj in cargo_in_hold:
                detail_item = QTreeWidgetItem(hold_item)
                detail_item.setText(2, f"  [OK] {obj.get('scu_amount', 0)} SCU {obj.get('cargo_type', 'Unknown')}")
                detail_item.setText(3, f"-> Deliver to {obj.get('deliver_to', '?')}")

                # Color by mission
                mission_id = obj.get('mission_id', '')
                if mission_id:
                    bg_color = self._get_mission_color(mission_id, mission_colors)
                    for col in range(5):
                        detail_item.setData(col, Qt.ItemDataRole.BackgroundRole, bg_color)
                        detail_item.setForeground(col, QBrush(QColor("#e0e0e0")))  # Light text

            hold_item.setExpanded(True)  # Expanded by default to show cargo

        if not self.current_route:
            return

        total_reward = 0

        for i, stop in enumerate(self.current_route.stops, 1):
            # Create stop item
            stop_item = QTreeWidgetItem(self.route_tree)
            stop_item.setData(0, Qt.ItemDataRole.UserRole, i)  # Store stop number

            # Stop number
            stop_item.setText(0, str(i))

            # Status - any stop in the route is pending (completed items are filtered out)
            status = "[TODO] Pending"
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

                    detail_item.setText(2, f"  [LOAD] Load: {pickup.scu_amount} SCU {pickup.cargo_type}")
                    detail_item.setText(3, f"-> Deliver to {pickup.deliver_to}{stop_indicator}")

                    # Store objective data for individual completion
                    detail_item.setData(0, Qt.ItemDataRole.UserRole + 1, {
                        'type': 'pickup',
                        'mission_id': getattr(pickup, 'mission_id', None),
                        'collect_from': pickup.collect_from,
                        'deliver_to': pickup.deliver_to,
                        'cargo_type': pickup.cargo_type,
                        'scu_amount': pickup.scu_amount
                    })

                    # Apply colored background for destination grouping
                    bg_color = self._get_destination_color(pickup.deliver_to, destination_colors)
                    for col in range(5):
                        detail_item.setData(col, Qt.ItemDataRole.BackgroundRole, bg_color)

            # Add detail rows for deliveries
            for delivery in stop.deliveries:
                detail_item = QTreeWidgetItem(stop_item)
                detail_item.setText(2, f"  [DELIVER] Deliver: {delivery.scu_amount} SCU {delivery.cargo_type}")
                detail_item.setText(3, f"<- From {delivery.collect_from}")

                # Store objective data for individual completion
                detail_item.setData(0, Qt.ItemDataRole.UserRole + 1, {
                    'type': 'delivery',
                    'mission_id': getattr(delivery, 'mission_id', None),
                    'collect_from': delivery.collect_from,
                    'deliver_to': delivery.deliver_to,
                    'cargo_type': delivery.cargo_type,
                    'scu_amount': delivery.scu_amount
                })

            # All stops in route are pending, keep expanded
            stop_item.setExpanded(True)

        # Update status - show remaining stops and completed missions
        total = len(self.current_route.stops)
        cargo_in_hold = self._get_cargo_in_hold()
        in_hold_count = len(cargo_in_hold)
        completed_missions = len(self.mission_manager.get_missions(status="completed"))
        self.status_label.setText(
            f"{total} stops remaining  |  {in_hold_count} items in hold  |  {completed_missions} missions done"
        )

    def _toggle_stop_completion(self, item: QTreeWidgetItem, column: int):
        """Mark stop or individual cargo item as complete on double-click."""
        # Check if this is an individual cargo item (detail row)
        obj_data = item.data(0, Qt.ItemDataRole.UserRole + 1)
        if obj_data:
            self._complete_single_objective(obj_data)
            self.refresh()
            return

        # Otherwise, check if this is a stop row
        stop_num = item.data(0, Qt.ItemDataRole.UserRole)
        if not stop_num:
            return  # Unknown row type

        if not self.current_route or stop_num > len(self.current_route.stops):
            return

        # All stops in the route are pending, so double-click marks complete
        self._complete_stop_and_missions(stop_num)
        # Re-optimize to move completed pickups to "In Cargo Hold"
        self.refresh()

    def _complete_single_objective(self, obj_data: dict):
        """Mark a single pickup or delivery objective as complete."""
        mission_id = obj_data.get('mission_id')
        if not mission_id:
            logger.warning("Cannot complete objective without mission_id")
            return

        obj_type = obj_data.get('type')
        collect_from = obj_data.get('collect_from')
        deliver_to = obj_data.get('deliver_to')
        cargo_type = obj_data.get('cargo_type')
        scu_amount = obj_data.get('scu_amount')

        logger.info(f"Completing single {obj_type}: {scu_amount} SCU {cargo_type} "
                   f"from {collect_from} to {deliver_to}")

        if obj_type == 'pickup':
            self.mission_manager.update_objective_completion(
                mission_id, collect_from, deliver_to,
                pickup_completed=True,
                cargo_type=cargo_type,
                scu_amount=scu_amount
            )
        elif obj_type == 'delivery':
            self.mission_manager.update_objective_completion(
                mission_id, collect_from, deliver_to,
                delivery_completed=True,
                cargo_type=cargo_type,
                scu_amount=scu_amount
            )
            # Check if mission is now fully complete
            self._check_mission_completion(mission_id)

    def _complete_stop_and_missions(self, stop_num: int):
        """Mark stop complete and update objective completion in missions."""
        if not self.current_route or stop_num > len(self.current_route.stops):
            return

        stop = self.current_route.stops[stop_num - 1]
        affected_missions = set()

        logger.info(f"Completing stop {stop_num} at {stop.location}")
        logger.info(f"  Pickups: {len(stop.pickups)}, Deliveries: {len(stop.deliveries)}")

        # Mark all pickups at this stop as completed
        for i, pickup in enumerate(stop.pickups):
            logger.info(f"  Pickup {i}: mission_id={getattr(pickup, 'mission_id', 'NONE')}, "
                       f"{pickup.scu_amount} SCU {pickup.cargo_type} from {pickup.collect_from}")
            if hasattr(pickup, 'mission_id') and pickup.mission_id:
                result = self.mission_manager.update_objective_completion(
                    pickup.mission_id, pickup.collect_from, pickup.deliver_to,
                    pickup_completed=True,
                    cargo_type=pickup.cargo_type,
                    scu_amount=pickup.scu_amount
                )
                logger.info(f"    -> update result: {result}")
                affected_missions.add(pickup.mission_id)
            else:
                logger.warning(f"    -> NO mission_id on pickup!")

        # Mark all deliveries at this stop as completed
        for delivery in stop.deliveries:
            if hasattr(delivery, 'mission_id') and delivery.mission_id:
                self.mission_manager.update_objective_completion(
                    delivery.mission_id, delivery.collect_from, delivery.deliver_to,
                    delivery_completed=True,
                    cargo_type=delivery.cargo_type,
                    scu_amount=delivery.scu_amount
                )
                affected_missions.add(delivery.mission_id)

        # Check if any affected missions are now fully complete
        for mission_id in affected_missions:
            self._check_mission_completion(mission_id)

    def _check_mission_completion(self, mission_id: str):
        """Check if all objectives of a mission are complete and update status."""
        mission = self.mission_manager.get_mission(mission_id)
        if not mission:
            return

        all_complete = True
        for obj in mission.get("objectives", []):
            pickup_done = obj.get("pickup_completed", False)
            delivery_done = obj.get("delivery_completed", False)
            if not (pickup_done and delivery_done):
                all_complete = False
                break

        if all_complete:
            self.mission_manager.update_status(mission_id, "completed")
            logger.info(f"Mission {mission_id} completed (all objectives done)")

    def _show_context_menu(self, position):
        """Show context menu for route stops and individual cargo items."""
        item = self.route_tree.itemAt(position)
        if not item:
            return

        menu = QMenu(self)

        # Check if this is an individual cargo item (detail row)
        obj_data = item.data(0, Qt.ItemDataRole.UserRole + 1)
        if obj_data:
            obj_type = obj_data.get('type', 'item')
            cargo_type = obj_data.get('cargo_type', 'Unknown')
            scu = obj_data.get('scu_amount', 0)

            if obj_type == 'pickup':
                action = QAction(f"[OK] Mark Loaded: {scu} SCU {cargo_type}", self)
            else:
                action = QAction(f"[OK] Mark Delivered: {scu} SCU {cargo_type}", self)

            action.triggered.connect(lambda: self._mark_single_complete(obj_data))
            menu.addAction(action)
            menu.exec(self.route_tree.viewport().mapToGlobal(position))
            return

        # Check if this is a stop row
        stop_num = item.data(0, Qt.ItemDataRole.UserRole)
        if not stop_num:
            return  # Unknown row type

        # All stops in the route are pending (completed items filtered out)
        action = QAction("[OK] Mark Stop Complete", self)
        action.triggered.connect(lambda: self._mark_complete(stop_num))

        menu.addAction(action)
        menu.exec(self.route_tree.viewport().mapToGlobal(position))

    def _mark_single_complete(self, obj_data: dict):
        """Mark a single cargo item as complete from context menu."""
        self._complete_single_objective(obj_data)
        self.refresh()

    def _mark_complete(self, stop_num: int):
        """Mark stop as complete."""
        self._complete_stop_and_missions(stop_num)
        # Re-optimize to move completed pickups to "In Cargo Hold"
        self.refresh()

    def _reset_progress(self):
        """Reset all progress tracking for active missions."""
        reply = QMessageBox.question(
            self,
            "Reset Progress",
            "Reset all stop completion tracking?\n\n"
            "This will clear pickup/delivery completion for all active missions.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            # Reset completion flags on all active mission objectives
            for mission in self.mission_manager.get_missions(status="active"):
                for obj in mission.get("objectives", []):
                    obj["pickup_completed"] = False
                    obj["delivery_completed"] = False
                self.mission_manager.update_mission(mission["id"], mission)
            self._update_route_display()
            logger.info("Progress tracking reset")

    def reload_config(self):
        """Reload configuration (called when config is saved in Settings tab)."""
        self.selected_ship_capacity = self.config.get("route_planner", "ship_capacity", default=96)
        self.route_quality = self.config.get("route_planner", "route_quality", default="best")

        # Update ship display
        ship_name = self.config.get("route_planner", "selected_ship", default="ARGO_RAFT")
        self.ship_label.setText(f"Ship: {ship_name} ({self.selected_ship_capacity} SCU)")

        logger.debug(f"Route planner config reloaded: {ship_name} ({self.selected_ship_capacity} SCU)")
