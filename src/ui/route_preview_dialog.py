"""
Route Preview Dialog
Shows optimized route with candidate mission included.
"""

from typing import List, Optional
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTreeWidget, QTreeWidgetItem, QGroupBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from src.domain.models import Mission
from src.services.vrp_solver import VRPSolver


class RoutePreviewDialog(QDialog):
    """Dialog showing route preview with candidate mission."""

    def __init__(
        self,
        candidate_mission: Mission,
        active_missions: List[Mission],
        ship_capacity: float,
        parent=None
    ):
        super().__init__(parent)
        self.candidate_mission = candidate_mission
        self.active_missions = active_missions
        self.ship_capacity = ship_capacity

        self.setWindowTitle("Route Preview - With New Mission")
        self.setModal(True)
        self.resize(700, 500)

        self._init_ui()
        self._calculate_and_display_route()

    def _init_ui(self):
        """Initialize UI components."""
        layout = QVBoxLayout()

        # Header
        header_label = QLabel("Optimized Route Preview")
        header_font = QFont()
        header_font.setPointSize(12)
        header_font.setBold(True)
        header_label.setFont(header_font)
        layout.addWidget(header_label)

        # Info label
        info_label = QLabel(
            f"This shows how the route would look if you accept the new mission. "
            f"Ship capacity: {self.ship_capacity:.0f} SCU"
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        # Route tree
        route_group = QGroupBox("Route Stops")
        route_layout = QVBoxLayout()

        self.route_tree = QTreeWidget()
        self.route_tree.setHeaderLabels([
            "Stop", "Action", "Cargo Details", "SCU Before", "SCU After"
        ])
        self.route_tree.setColumnWidth(0, 50)
        self.route_tree.setColumnWidth(1, 100)
        self.route_tree.setColumnWidth(2, 300)
        self.route_tree.setColumnWidth(3, 80)
        self.route_tree.setColumnWidth(4, 80)

        route_layout.addWidget(self.route_tree)
        route_group.setLayout(route_layout)
        layout.addWidget(route_group)

        # Summary
        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        button_layout.addWidget(close_button)

        layout.addLayout(button_layout)

        self.setLayout(layout)

    def _calculate_and_display_route(self):
        """Calculate optimized route and display in tree."""
        try:
            # Create VRP solver
            solver = VRPSolver(ship_capacity=int(self.ship_capacity))

            # Prepare missions (active + candidate)
            all_missions = self.active_missions + [self.candidate_mission]

            # Solve VRP
            route = solver.solve(all_missions, optimization_level='basic')

            if route:
                self._display_route(route)
            else:
                self._display_error("Could not generate route. Missions may not be feasible.")

        except Exception as e:
            self._display_error(f"Error calculating route: {str(e)}")

    def _display_route(self, route):
        """Display route in tree widget."""
        self.route_tree.clear()

        total_stops = len(route.stops)
        max_cargo = 0.0

        for idx, stop in enumerate(route.stops, 1):
            # Create stop item
            stop_item = QTreeWidgetItem([
                f"#{idx}",
                stop.location,
                "",
                f"{stop.cargo_before:.1f}",
                f"{stop.cargo_after:.1f}"
            ])

            # Track max cargo
            max_cargo = max(max_cargo, stop.cargo_after)

            # Bold font for stop location
            font = stop_item.font(1)
            font.setBold(True)
            stop_item.setFont(1, font)

            # Add pickups
            for pickup in stop.pickups:
                # Check if this is from the candidate mission
                is_new = pickup.mission_id == self.candidate_mission.id
                mission_marker = " [NEW]" if is_new else ""

                pickup_item = QTreeWidgetItem([
                    "",
                    "  Pickup",
                    f"+{pickup.scu_amount:.1f} SCU to {pickup.deliver_to}{mission_marker}",
                    "",
                    ""
                ])

                # Highlight new mission items
                if is_new:
                    for col in range(5):
                        pickup_item.setForeground(col, Qt.GlobalColor.darkGreen)

                stop_item.addChild(pickup_item)

            # Add deliveries
            for delivery in stop.deliveries:
                # Check if this is from the candidate mission
                is_new = delivery.mission_id == self.candidate_mission.id
                mission_marker = " [NEW]" if is_new else ""

                delivery_item = QTreeWidgetItem([
                    "",
                    "  Delivery",
                    f"-{delivery.scu_amount:.1f} SCU from {delivery.collect_from}{mission_marker}",
                    "",
                    ""
                ])

                # Highlight new mission items
                if is_new:
                    for col in range(5):
                        delivery_item.setForeground(col, Qt.GlobalColor.darkGreen)

                stop_item.addChild(delivery_item)

            self.route_tree.addTopLevelItem(stop_item)
            stop_item.setExpanded(True)

        # Update summary
        capacity_utilization = (max_cargo / self.ship_capacity * 100) if self.ship_capacity > 0 else 0
        summary_text = (
            f"<b>Route Summary:</b> {total_stops} stops, "
            f"Peak cargo: {max_cargo:.1f} SCU ({capacity_utilization:.1f}% capacity). "
            f"<span style='color: green;'>Items marked [NEW] are from the candidate mission.</span>"
        )
        self.summary_label.setText(summary_text)

    def _display_error(self, message: str):
        """Display error message."""
        self.route_tree.clear()
        error_item = QTreeWidgetItem(["Error", message, "", "", ""])
        error_item.setForeground(0, Qt.GlobalColor.red)
        self.route_tree.addTopLevelItem(error_item)
        self.summary_label.setText(f"<span style='color: red;'>{message}</span>")
