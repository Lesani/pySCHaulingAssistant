"""
Route Finder tab for PyQt6.

Find optimal routes from the mission scan database based on user-defined filters
and optimization goals.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QPushButton, QSpinBox, QComboBox, QCheckBox, QLineEdit,
    QTreeWidget, QTreeWidgetItem, QHeaderView, QCompleter,
    QSplitter, QFrame, QProgressBar, QSlider,
    QApplication, QScrollArea
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor

from typing import Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from src.sync_service import SyncService

from src.mission_scan_db import MissionScanDB, CONTRACTOR_CANONICAL
from src.config import Config
from src.location_autocomplete import LocationMatcher
from src.ship_profiles import ShipManager, SHIP_PROFILES
from src.services.route_finder_service import (
    RouteFinderService, RouteFinderFilters, OptimizationGoal,
    OptimizationWeights, OPTIMIZATION_PRESETS, SearchStrategy,
    CandidateRoute, RANK_HIERARCHY, ContractorRankFilter
)
from src.services.location_type_classifier import LocationType, LocationTypeClassifier
from src.logger import get_logger

logger = get_logger()


class SortableTreeWidgetItem(QTreeWidgetItem):
    """Tree widget item with proper numeric sorting for route columns."""

    # Column indices that should be sorted numerically
    NUMERIC_COLUMNS = {1, 2, 3, 4, 5}  # Reward, Stops, SCU, Missions, Score

    def __lt__(self, other: QTreeWidgetItem) -> bool:
        """Compare items for sorting."""
        tree = self.treeWidget()
        if not tree:
            return super().__lt__(other)

        col = tree.sortColumn()

        if col in self.NUMERIC_COLUMNS:
            # Extract numeric value from text (remove formatting like commas, aUEC, etc.)
            self_val = self._extract_number(self.text(col))
            other_val = self._extract_number(other.text(col))
            return self_val < other_val

        return super().__lt__(other)

    def _extract_number(self, text: str) -> float:
        """Extract numeric value from formatted text."""
        # Remove common suffixes and formatting
        cleaned = text.replace(",", "").replace(" aUEC", "").replace(" SCU", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return 0.0


class StopTreeWidgetItem(QTreeWidgetItem):
    """Tree widget item for stops with numeric prefix sorting."""

    def __lt__(self, other: QTreeWidgetItem) -> bool:
        """Compare items by extracting numeric prefix (e.g., '5. Location')."""
        tree = self.treeWidget()
        if not tree:
            return super().__lt__(other)

        col = tree.sortColumn()
        if col == 0:
            # Extract leading number from "N. Location" format
            self_num = self._extract_prefix_number(self.text(0))
            other_num = self._extract_prefix_number(other.text(0))
            if self_num is not None and other_num is not None:
                return self_num < other_num

        return super().__lt__(other)

    def _extract_prefix_number(self, text: str) -> int | None:
        """Extract leading number before the first dot."""
        dot_idx = text.find(".")
        if dot_idx > 0:
            try:
                return int(text[:dot_idx])
            except ValueError:
                pass
        return None


class RouteFinderWorker(QThread):
    """Background worker for route finding."""

    finished = pyqtSignal(list, int)  # List[CandidateRoute], pool_size
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(
        self,
        service: RouteFinderService,
        filters: RouteFinderFilters,
        weights: OptimizationWeights,
        strategy: SearchStrategy = SearchStrategy.FAST,
        offset: int = 0,
        max_results: int = 10
    ):
        super().__init__()
        self.service = service
        self.filters = filters
        self.weights = weights
        self.strategy = strategy
        self.offset = offset
        self.max_results = max_results

    def run(self):
        try:
            self.progress.emit("Filtering missions...")
            routes = self.service.find_best_routes(
                self.filters, self.weights,
                max_results=self.max_results,
                strategy=self.strategy,
                offset=self.offset
            )
            pool_size = self.service.last_pool_size
            self.finished.emit(routes, pool_size)
        except Exception as e:
            logger.error(f"Route finder error: {e}")
            self.error.emit(str(e))


class RouteFinderTab(QWidget):
    """Tab for finding optimal routes from mission scans."""

    def __init__(
        self,
        config: Config,
        scan_db: MissionScanDB,
        location_matcher: LocationMatcher,
        ship_manager: ShipManager = None,
        sync_service: Optional["SyncService"] = None
    ):
        super().__init__()

        self.config = config
        self.scan_db = scan_db
        self.location_matcher = location_matcher
        self.ship_manager = ship_manager or ShipManager()
        self.sync_service = sync_service
        self.classifier = LocationTypeClassifier()

        self.service = RouteFinderService(
            scan_db=scan_db,
            location_classifier=self.classifier,
            ship_manager=self.ship_manager,
            config=config
        )

        self._worker: Optional[RouteFinderWorker] = None
        self._current_routes: List[CandidateRoute] = []
        self._last_filters: Optional[RouteFinderFilters] = None
        self._last_weights: Optional[OptimizationWeights] = None
        self._last_strategy: Optional[SearchStrategy] = None
        self._route_offset: int = 0
        self._last_pool_size: int = 0

        self._setup_ui()
        self._load_initial_data()

    def _setup_ui(self):
        """Setup the route finder UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Main splitter between filters and results
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left panel - Filters
        left_widget = QWidget()
        left_widget.setMinimumWidth(460)
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # Scroll area for filters
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        filters_widget = QWidget()
        filters_layout = QVBoxLayout(filters_widget)
        filters_layout.setSpacing(12)

        # Basic filters
        basic_group = QGroupBox("Basic Filters")
        basic_layout = QVBoxLayout()
        basic_layout.setSpacing(8)

        # Starting location
        start_layout = QHBoxLayout()
        start_layout.addWidget(QLabel("Start From:"))
        self.start_location = QLineEdit()
        self.start_location.setPlaceholderText("Any location (optional)")
        locations = self.location_matcher.get_scannable_locations()
        completer = QCompleter(locations)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.start_location.setCompleter(completer)
        start_layout.addWidget(self.start_location, 1)
        basic_layout.addLayout(start_layout)

        # Max stops
        stops_layout = QHBoxLayout()
        stops_layout.addWidget(QLabel("Max Stops:"))
        self.max_stops = QSpinBox()
        self.max_stops.setRange(1, 200)
        self.max_stops.setValue(50)
        stops_layout.addWidget(self.max_stops)
        stops_layout.addStretch()
        basic_layout.addLayout(stops_layout)

        # Round trip
        self.round_trip = QCheckBox("Round Trip (return to start)")
        basic_layout.addWidget(self.round_trip)

        basic_group.setLayout(basic_layout)
        filters_layout.addWidget(basic_group)

        # Location type filters
        loc_type_group = QGroupBox("Location Types")
        loc_type_layout = QVBoxLayout()

        self.location_type_checks = {}
        type_display_names = {
            LocationType.ORBITAL_STATION: "Orbital Stations",
            LocationType.LAGRANGE_STATION: "Lagrange Stations",
            LocationType.DISTRIBUTION_CENTER: "Distribution Centers",
            LocationType.CITY: "Cities",
            LocationType.OUTPOST: "Outposts",
            LocationType.MINING_FACILITY: "Mining Facilities",
            LocationType.SCRAPYARD: "Scrapyards",
            LocationType.FARMING_OUTPOST: "Farming Outposts",
        }

        # Default checked: space types
        default_checked = [
            LocationType.ORBITAL_STATION,
            LocationType.LAGRANGE_STATION,
            LocationType.DISTRIBUTION_CENTER,
        ]

        for loc_type in LocationType.all_types():
            cb = QCheckBox(type_display_names.get(loc_type, loc_type))
            cb.setChecked(loc_type in default_checked)
            self.location_type_checks[loc_type] = cb
            loc_type_layout.addWidget(cb)

        # Quick select buttons
        quick_layout = QHBoxLayout()
        all_btn = QPushButton("All")
        all_btn.clicked.connect(lambda: self._set_all_location_types(True))
        space_btn = QPushButton("Space Only")
        space_btn.clicked.connect(self._set_space_only)
        ground_btn = QPushButton("Ground Only")
        ground_btn.clicked.connect(self._set_ground_only)
        quick_layout.addWidget(all_btn)
        quick_layout.addWidget(space_btn)
        quick_layout.addWidget(ground_btn)
        loc_type_layout.addLayout(quick_layout)

        loc_type_group.setLayout(loc_type_layout)
        filters_layout.addWidget(loc_type_group)

        # System filters
        system_group = QGroupBox("Systems")
        system_layout = QHBoxLayout()

        self.system_checks = {}
        for system in ["Stanton", "Nyx", "Pyro"]:
            cb = QCheckBox(system)
            cb.setChecked(system == "Stanton")  # Default to Stanton only
            self.system_checks[system] = cb
            system_layout.addWidget(cb)

        system_group.setLayout(system_layout)
        filters_layout.addWidget(system_group)

        # Contractor filters with per-contractor rank selection
        contractor_group = QGroupBox("Contractors")
        contractor_layout = QVBoxLayout()
        contractor_layout.setSpacing(4)

        # Store contractor widgets: {contractor_name: (checkbox, min_rank_combo, max_rank_combo)}
        self.contractor_widgets = {}

        # Build dynamically from CONTRACTOR_CANONICAL
        for contractor_name in sorted(CONTRACTOR_CANONICAL.keys()):
            # Row for each contractor
            row_layout = QHBoxLayout()
            row_layout.setSpacing(4)

            # Checkbox for contractor
            cb = QCheckBox(contractor_name)
            cb.setChecked(True)  # All contractors enabled by default
            cb.setMinimumWidth(140)
            row_layout.addWidget(cb)

            # Min rank
            min_rank = QComboBox()
            min_rank.setFixedWidth(90)
            min_rank.addItem("Any")
            for rank in RANK_HIERARCHY:
                min_rank.addItem(rank)
            row_layout.addWidget(min_rank)

            # "to" label
            to_label = QLabel("-")
            to_label.setFixedWidth(15)
            to_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row_layout.addWidget(to_label)

            # Max rank
            max_rank = QComboBox()
            max_rank.setFixedWidth(90)
            max_rank.addItem("Any")
            for rank in RANK_HIERARCHY:
                max_rank.addItem(rank)
            row_layout.addWidget(max_rank)

            row_layout.addStretch()
            contractor_layout.addLayout(row_layout)

            # Store references
            self.contractor_widgets[contractor_name] = (cb, min_rank, max_rank)

            # Connect checkbox to enable/disable rank combos
            cb.toggled.connect(
                lambda checked, mr=min_rank, xr=max_rank: self._on_contractor_toggled(checked, mr, xr)
            )

        # Quick select buttons
        contractor_btn_layout = QHBoxLayout()
        all_contractors_btn = QPushButton("All")
        all_contractors_btn.clicked.connect(lambda: self._set_all_contractors(True))
        none_contractors_btn = QPushButton("None")
        none_contractors_btn.clicked.connect(lambda: self._set_all_contractors(False))
        contractor_btn_layout.addWidget(all_contractors_btn)
        contractor_btn_layout.addWidget(none_contractors_btn)
        contractor_btn_layout.addStretch()
        contractor_layout.addLayout(contractor_btn_layout)

        contractor_group.setLayout(contractor_layout)
        filters_layout.addWidget(contractor_group)

        # Reward filter (separate from contractors)
        reward_group = QGroupBox("Reward Filter")
        reward_layout = QHBoxLayout()
        reward_layout.addWidget(QLabel("Min:"))
        self.min_reward = QSpinBox()
        self.min_reward.setFixedWidth(110)
        self.min_reward.setRange(0, 10000000)
        self.min_reward.setSingleStep(10000)
        self.min_reward.setSpecialValueText("Any")
        self.min_reward.setSuffix(" aUEC")
        reward_layout.addWidget(self.min_reward)
        reward_layout.addWidget(QLabel("Max:"))
        self.max_reward = QSpinBox()
        self.max_reward.setFixedWidth(110)
        self.max_reward.setRange(0, 10000000)
        self.max_reward.setSingleStep(10000)
        self.max_reward.setSpecialValueText("Any")
        self.max_reward.setSuffix(" aUEC")
        reward_layout.addWidget(self.max_reward)
        reward_layout.addStretch()
        reward_group.setLayout(reward_layout)
        filters_layout.addWidget(reward_group)

        # Ship selection
        ship_group = QGroupBox("Ship")
        ship_layout = QVBoxLayout()

        self.ship_combo = QComboBox()
        # Populate ships sorted by capacity
        ships = sorted(SHIP_PROFILES.items(), key=lambda x: x[1].cargo_capacity_scu)
        for key, profile in ships:
            self.ship_combo.addItem(
                f"{profile.name} ({profile.cargo_capacity_scu} SCU)",
                key
            )
        # Default to Zeus CL if available
        zeus_idx = self.ship_combo.findData("RSI_ZEUS_MK2_CL")
        if zeus_idx >= 0:
            self.ship_combo.setCurrentIndex(zeus_idx)
        ship_layout.addWidget(self.ship_combo)

        ship_group.setLayout(ship_layout)
        filters_layout.addWidget(ship_group)

        # Search strategy
        strategy_group = QGroupBox("Search Strategy")
        strategy_layout = QVBoxLayout()

        self.strategy_combo = QComboBox()
        self.strategy_combo.addItem(
            SearchStrategy.display_name(SearchStrategy.FAST),
            SearchStrategy.FAST
        )
        self.strategy_combo.addItem(
            SearchStrategy.display_name(SearchStrategy.BETTER),
            SearchStrategy.BETTER
        )
        self.strategy_combo.setToolTip(
            "Fast: Quick search prioritizing location sharing\n"
            "Better: Thorough beam search (slower but finds better routes)"
        )
        strategy_layout.addWidget(self.strategy_combo)

        strategy_group.setLayout(strategy_layout)
        filters_layout.addWidget(strategy_group)

        # Optimization weights
        goal_group = QGroupBox("Optimization Weights")
        goal_layout = QVBoxLayout()
        goal_layout.setSpacing(4)

        self.weight_sliders = {}
        self.weight_labels = {}

        slider_configs = [
            (OptimizationGoal.MAX_REWARD, "Max Reward", 100),
            (OptimizationGoal.FEWEST_STOPS, "Fewest Stops", 0),
            (OptimizationGoal.MIN_DISTANCE, "Min Distance", 0),
            (OptimizationGoal.BEST_REWARD_PER_STOP, "Reward/Stop", 0),
            (OptimizationGoal.BEST_REWARD_PER_SCU, "Reward/SCU", 0),
        ]

        for goal, label, default_val in slider_configs:
            row = QHBoxLayout()
            row.setSpacing(8)

            name_label = QLabel(f"{label}:")
            name_label.setMinimumWidth(85)
            row.addWidget(name_label)

            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, 100)
            slider.setValue(default_val)
            slider.setTickPosition(QSlider.TickPosition.NoTicks)
            slider.valueChanged.connect(self._on_weight_changed)
            self.weight_sliders[goal] = slider
            row.addWidget(slider, 1)

            value_label = QLabel(f"{default_val}%")
            value_label.setMinimumWidth(35)
            value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.weight_labels[goal] = value_label
            row.addWidget(value_label)

            goal_layout.addLayout(row)

        # Preset buttons
        preset_layout = QHBoxLayout()
        preset_layout.setSpacing(4)
        for preset_name in OPTIMIZATION_PRESETS.keys():
            btn = QPushButton(preset_name)
            btn.setFixedHeight(24)
            btn.clicked.connect(lambda checked, name=preset_name: self._apply_preset(name))
            preset_layout.addWidget(btn)
        goal_layout.addLayout(preset_layout)

        goal_group.setLayout(goal_layout)
        filters_layout.addWidget(goal_group)

        # Action buttons
        btn_layout = QHBoxLayout()
        self.find_btn = QPushButton("Find Routes")
        self.find_btn.setProperty("class", "primary")
        self.find_btn.clicked.connect(self._find_routes)
        btn_layout.addWidget(self.find_btn)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self._clear_filters)
        btn_layout.addWidget(self.clear_btn)

        filters_layout.addLayout(btn_layout)

        # Add stretch at bottom
        filters_layout.addStretch()

        scroll.setWidget(filters_widget)
        left_layout.addWidget(scroll)

        splitter.addWidget(left_widget)

        # Right panel - Results
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # Results header
        results_header = QHBoxLayout()
        self.results_label = QLabel("Routes will appear here")
        self.results_label.setProperty("class", "heading")
        results_header.addWidget(self.results_label)
        results_header.addStretch()

        self.more_btn = QPushButton("More")
        self.more_btn.clicked.connect(self._load_more_routes)
        self.more_btn.hide()  # Hidden until results are shown
        results_header.addWidget(self.more_btn)

        right_layout.addLayout(results_header)

        # Progress bar (hidden by default)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate
        self.progress_bar.hide()
        right_layout.addWidget(self.progress_bar)

        # Results tree
        self.results_tree = QTreeWidget()
        self.results_tree.setHeaderLabels([
            "Route", "Reward", "Stops", "SCU", "Missions", "Score"
        ])
        self.results_tree.setAlternatingRowColors(True)
        self.results_tree.setRootIsDecorated(True)
        self.results_tree.setSortingEnabled(True)
        self.results_tree.itemExpanded.connect(self._on_item_expanded)

        header = self.results_tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)

        right_layout.addWidget(self.results_tree, 1)

        splitter.addWidget(right_widget)

        # Set splitter sizes (filters narrower than results)
        splitter.setSizes([400, 600])

        layout.addWidget(splitter, 1)

        # Status bar
        self.status_label = QLabel("Ready")
        self.status_label.setProperty("class", "muted")
        layout.addWidget(self.status_label)

    def _load_initial_data(self):
        """Load initial data and update statistics."""
        stats = self.service.get_statistics()
        self.status_label.setText(
            f"Database: {stats['total_missions']} missions | "
            f"{stats['unique_locations']} locations"
        )

    def _set_all_location_types(self, checked: bool):
        """Set all location type checkboxes."""
        for cb in self.location_type_checks.values():
            cb.setChecked(checked)

    def _set_space_only(self):
        """Set only space location types."""
        space_types = LocationType.space_only_types()
        for loc_type, cb in self.location_type_checks.items():
            cb.setChecked(loc_type in space_types)

    def _set_ground_only(self):
        """Set only ground location types."""
        ground_types = LocationType.ground_types()
        for loc_type, cb in self.location_type_checks.items():
            cb.setChecked(loc_type in ground_types)

    def _on_contractor_toggled(self, checked: bool, min_rank: QComboBox, max_rank: QComboBox):
        """Handle contractor checkbox toggle - enable/disable rank combos."""
        min_rank.setEnabled(checked)
        max_rank.setEnabled(checked)

    def _set_all_contractors(self, checked: bool):
        """Set all contractor checkboxes."""
        for cb, min_rank, max_rank in self.contractor_widgets.values():
            cb.setChecked(checked)

    def _clear_filters(self):
        """Reset filters to defaults."""
        self.start_location.clear()
        self.max_stops.setValue(50)
        self.round_trip.setChecked(False)
        self._set_space_only()
        for cb in self.system_checks.values():
            cb.setChecked(False)
        self.system_checks["Stanton"].setChecked(True)

        # Reset contractor filters
        for cb, min_rank, max_rank in self.contractor_widgets.values():
            cb.setChecked(True)
            min_rank.setCurrentIndex(0)  # "Any"
            max_rank.setCurrentIndex(0)  # "Any"

        self.min_reward.setValue(0)
        self.max_reward.setValue(0)

        # Reset sliders to Max Profit preset
        self._apply_preset("Max Profit")

    def _get_filters(self) -> RouteFinderFilters:
        """Get current filter settings."""
        # Get allowed location types
        allowed_types = [
            loc_type for loc_type, cb in self.location_type_checks.items()
            if cb.isChecked()
        ]

        # Get allowed systems
        allowed_systems = [
            system for system, cb in self.system_checks.items()
            if cb.isChecked()
        ]

        # Get contractor filters (only checked contractors with their rank requirements)
        contractor_filters = {}
        for contractor_name, (cb, min_rank_combo, max_rank_combo) in self.contractor_widgets.items():
            if cb.isChecked():
                min_rank_text = min_rank_combo.currentText()
                max_rank_text = max_rank_combo.currentText()
                contractor_filters[contractor_name] = ContractorRankFilter(
                    min_rank=min_rank_text if min_rank_text != "Any" else None,
                    max_rank=max_rank_text if max_rank_text != "Any" else None
                )

        # If all contractors are selected with no rank restrictions, use None (allow all)
        if len(contractor_filters) == len(self.contractor_widgets):
            all_any = all(
                f.min_rank is None and f.max_rank is None
                for f in contractor_filters.values()
            )
            if all_any:
                contractor_filters = None

        # Get reward range
        min_reward = self.min_reward.value() if self.min_reward.value() > 0 else None
        max_reward = self.max_reward.value() if self.max_reward.value() > 0 else None

        # Get ship
        ship_key = self.ship_combo.currentData() or "RSI_ZEUS_MK2_CL"

        # Get starting location
        starting = self.start_location.text().strip() or None

        return RouteFinderFilters(
            max_stops=self.max_stops.value(),
            starting_location=starting,
            allowed_location_types=allowed_types,
            allowed_systems=allowed_systems,
            min_reward=min_reward,
            max_reward=max_reward,
            ship_key=ship_key,
            round_trip=self.round_trip.isChecked(),
            contractor_filters=contractor_filters
        )

    def _on_weight_changed(self):
        """Update weight label when slider moves."""
        for goal, slider in self.weight_sliders.items():
            self.weight_labels[goal].setText(f"{slider.value()}%")

    def _apply_preset(self, preset_name: str):
        """Apply a preset weight configuration."""
        preset = OPTIMIZATION_PRESETS.get(preset_name)
        if not preset:
            return

        self.weight_sliders[OptimizationGoal.MAX_REWARD].setValue(preset.max_reward)
        self.weight_sliders[OptimizationGoal.FEWEST_STOPS].setValue(preset.fewest_stops)
        self.weight_sliders[OptimizationGoal.MIN_DISTANCE].setValue(preset.min_distance)
        self.weight_sliders[OptimizationGoal.BEST_REWARD_PER_STOP].setValue(preset.reward_per_stop)
        self.weight_sliders[OptimizationGoal.BEST_REWARD_PER_SCU].setValue(preset.reward_per_scu)

    def _get_weights(self) -> OptimizationWeights:
        """Get current optimization weights from sliders."""
        return OptimizationWeights(
            max_reward=self.weight_sliders[OptimizationGoal.MAX_REWARD].value(),
            fewest_stops=self.weight_sliders[OptimizationGoal.FEWEST_STOPS].value(),
            min_distance=self.weight_sliders[OptimizationGoal.MIN_DISTANCE].value(),
            reward_per_stop=self.weight_sliders[OptimizationGoal.BEST_REWARD_PER_STOP].value(),
            reward_per_scu=self.weight_sliders[OptimizationGoal.BEST_REWARD_PER_SCU].value(),
        )

    def _get_strategy(self) -> SearchStrategy:
        """Get selected search strategy."""
        return self.strategy_combo.currentData() or SearchStrategy.FAST

    def _find_routes(self):
        """Start route finding."""
        if self._worker and self._worker.isRunning():
            return  # Already running

        filters = self._get_filters()
        weights = self._get_weights()
        strategy = self._get_strategy()

        # Validate
        if not filters.allowed_location_types:
            self.status_label.setText("Error: Select at least one location type")
            return
        if not filters.allowed_systems:
            self.status_label.setText("Error: Select at least one system")
            return
        # Check if at least one contractor is selected
        any_contractor = any(cb.isChecked() for cb, _, _ in self.contractor_widgets.values())
        if not any_contractor:
            self.status_label.setText("Error: Select at least one contractor")
            return
        if not weights.is_valid():
            self.status_label.setText("Error: Set at least one optimization weight > 0")
            return

        # Save state for "More" functionality
        self._last_filters = filters
        self._last_weights = weights
        self._last_strategy = strategy
        self._route_offset = 0
        self._last_pool_size = 0
        self._current_routes = []  # Clear previous results

        # Start worker
        self.find_btn.setEnabled(False)
        self.find_btn.setText("Searching...")
        self.more_btn.hide()
        self.progress_bar.show()
        self.results_tree.clear()
        self.results_label.setText("Searching for routes...")

        self._worker = RouteFinderWorker(
            self.service, filters, weights, strategy,
            offset=0, max_results=10
        )
        self._worker.finished.connect(self._on_routes_found)
        self._worker.error.connect(self._on_route_error)
        self._worker.progress.connect(self._on_progress)
        self._worker.start()

    def _on_progress(self, message: str):
        """Handle progress updates."""
        self.status_label.setText(message)

    def _on_routes_found(self, routes: List[CandidateRoute], pool_size: int):
        """Handle route finding completion."""
        self.find_btn.setEnabled(True)
        self.find_btn.setText("Find Routes")
        self.progress_bar.hide()

        self._current_routes.extend(routes)
        self._route_offset += len(routes)
        self._last_pool_size = pool_size

        if not self._current_routes:
            self.results_label.setText("No routes found")
            self.status_label.setText("No routes match your criteria. Try adjusting filters.")
            self.more_btn.hide()
            return

        self.results_label.setText(f"Found {len(self._current_routes)} route(s)")
        self._display_routes(self._current_routes, apply_default_sort=True)

        # Show "More" button if we got a full batch (more may be available)
        if len(routes) >= 10:
            self.more_btn.show()
        else:
            self.more_btn.hide()

        total_missions = sum(len(r.missions) for r in self._current_routes)
        self.status_label.setText(f"Found {len(self._current_routes)} routes from {pool_size} missions (using {total_missions})")

    def _on_route_error(self, error: str):
        """Handle route finding error."""
        self.find_btn.setEnabled(True)
        self.find_btn.setText("Find Routes")
        self.progress_bar.hide()
        self.more_btn.hide()
        self.results_label.setText("Error finding routes")
        self.status_label.setText(f"Error: {error}")

    def _load_more_routes(self):
        """Load more routes using saved search state."""
        if self._worker and self._worker.isRunning():
            return  # Already running

        if not self._last_filters or not self._last_weights:
            return  # No previous search

        self.find_btn.setEnabled(False)
        self.more_btn.setEnabled(False)
        self.more_btn.setText("Loading...")
        self.progress_bar.show()
        self.status_label.setText("Loading more routes...")

        self._worker = RouteFinderWorker(
            self.service, self._last_filters, self._last_weights, self._last_strategy,
            offset=self._route_offset, max_results=10
        )
        self._worker.finished.connect(self._on_more_routes_found)
        self._worker.error.connect(self._on_route_error)
        self._worker.progress.connect(self._on_progress)
        self._worker.start()

    def _on_more_routes_found(self, routes: List[CandidateRoute], pool_size: int):
        """Handle more routes loaded."""
        self.find_btn.setEnabled(True)
        self.more_btn.setEnabled(True)
        self.more_btn.setText("More")
        self.progress_bar.hide()

        if not routes:
            self.more_btn.hide()
            self.status_label.setText("No more routes available")
            return

        self._current_routes.extend(routes)
        self._route_offset += len(routes)
        self._last_pool_size = pool_size

        self.results_label.setText(f"Found {len(self._current_routes)} route(s)")
        self._display_routes(self._current_routes)

        # Hide "More" if we got less than a full batch
        if len(routes) < 10:
            self.more_btn.hide()

        total_missions = sum(len(r.missions) for r in self._current_routes)
        self.status_label.setText(f"Found {len(self._current_routes)} routes from {pool_size} missions (using {total_missions})")

    def _display_routes(self, routes: List[CandidateRoute], apply_default_sort: bool = False):
        """Display routes in the results tree."""
        self.results_tree.clear()
        # Disable sorting while populating to avoid performance issues
        self.results_tree.setSortingEnabled(False)

        for i, candidate in enumerate(routes, 1):
            metrics = candidate.metrics
            route = candidate.route

            # Create top-level item with sortable support
            item = SortableTreeWidgetItem()
            item.setText(0, f"Route #{i}")
            item.setText(1, f"{metrics.total_reward:,.0f} aUEC")
            item.setText(2, str(metrics.stop_count))
            item.setText(3, str(metrics.total_scu))
            item.setText(4, str(metrics.mission_count))
            item.setText(5, f"{candidate.score:,.1f}")

            # Store route data
            item.setData(0, Qt.ItemDataRole.UserRole, candidate)

            # Add placeholder child (will be populated on expand)
            placeholder = QTreeWidgetItem()
            placeholder.setText(0, "Loading...")
            item.addChild(placeholder)

            # Color based on ranking
            if i == 1:
                for col in range(6):
                    item.setBackground(col, QColor(76, 175, 80, 50))  # Green tint

            self.results_tree.addTopLevelItem(item)

        # Re-enable sorting after populating
        self.results_tree.setSortingEnabled(True)

        # Apply default sort based on dominant optimization goal
        if apply_default_sort and self._last_weights:
            goal = self._last_weights.get_dominant_goal()
            # Map goals to columns and sort order
            # Columns: 0=Route, 1=Reward, 2=Stops, 3=SCU, 4=Missions, 5=Score
            sort_config = {
                OptimizationGoal.MAX_REWARD: (1, Qt.SortOrder.DescendingOrder),
                OptimizationGoal.FEWEST_STOPS: (2, Qt.SortOrder.AscendingOrder),
                OptimizationGoal.MIN_DISTANCE: (5, Qt.SortOrder.DescendingOrder),
                OptimizationGoal.BEST_REWARD_PER_STOP: (5, Qt.SortOrder.DescendingOrder),
                OptimizationGoal.BEST_REWARD_PER_SCU: (5, Qt.SortOrder.DescendingOrder),
            }
            col, order = sort_config.get(goal, (5, Qt.SortOrder.DescendingOrder))
            self.results_tree.sortByColumn(col, order)

    def _on_item_expanded(self, item: QTreeWidgetItem):
        """Handle item expansion - populate details."""
        # Check if already populated
        if item.childCount() > 0:
            first_child = item.child(0)
            if first_child.text(0) != "Loading...":
                return  # Already populated

        # Get candidate data
        candidate = item.data(0, Qt.ItemDataRole.UserRole)
        if not candidate:
            return

        # Remove placeholder
        item.takeChildren()

        # Collect all items to set spanning after adding to tree
        items_to_span = []

        # Add stops section
        stops_item = QTreeWidgetItem(item)
        stops_item.setText(0, "== STOPS ==")
        items_to_span.append(stops_item)

        for stop in candidate.route.stops:
            stop_item = StopTreeWidgetItem(stops_item)
            stop_item.setText(0, f"{stop.stop_number}. {stop.location}")
            items_to_span.append(stop_item)

            # Add pickup/delivery details
            if stop.pickups:
                for obj in stop.pickups:
                    pickup_item = QTreeWidgetItem(stop_item)
                    pickup_item.setText(0, f"    [+] LOAD: {obj.scu_amount} SCU {obj.cargo_type}")
                    pickup_item.setForeground(0, QColor(76, 175, 80))  # Green
                    items_to_span.append(pickup_item)

            if stop.deliveries:
                for obj in stop.deliveries:
                    delivery_item = QTreeWidgetItem(stop_item)
                    delivery_item.setText(0, f"    [-] DELIVER: {obj.scu_amount} SCU {obj.cargo_type}")
                    delivery_item.setForeground(0, QColor(244, 67, 54))  # Red
                    items_to_span.append(delivery_item)

            # Cargo state
            cargo_item = QTreeWidgetItem(stop_item)
            cargo_item.setText(0, f"    Cargo: {stop.cargo_before} -> {stop.cargo_after} SCU")
            cargo_item.setForeground(0, QColor(158, 158, 158))  # Gray
            items_to_span.append(cargo_item)

        stops_item.setExpanded(True)

        # Add missions section
        missions_item = QTreeWidgetItem(item)
        missions_item.setText(0, f"== MISSIONS ({len(candidate.missions)}) ==")
        items_to_span.append(missions_item)

        for mission_scan in candidate.missions:
            mission_data = mission_scan.get("mission_data", {})
            reward = mission_data.get("reward", 0)
            rank = mission_data.get("rank", "")

            mission_item = QTreeWidgetItem(missions_item)
            if rank:
                mission_item.setText(0, f"[{rank}] {reward:,.0f} aUEC")
            else:
                mission_item.setText(0, f"{reward:,.0f} aUEC")
            items_to_span.append(mission_item)

            # Add objectives
            for obj in mission_data.get("objectives", []):
                obj_item = QTreeWidgetItem(mission_item)
                obj_item.setText(
                    0,
                    f"    {obj.get('scu_amount', 0)} SCU: "
                    f"{obj.get('collect_from', '?')} -> {obj.get('deliver_to', '?')}"
                )
                items_to_span.append(obj_item)

        # Add metrics section
        metrics_item = QTreeWidgetItem(item)
        metrics_item.setText(0, "== METRICS ==")
        items_to_span.append(metrics_item)

        metrics = candidate.metrics
        metrics_details = [
            f"Total Reward: {metrics.total_reward:,.0f} aUEC",
            f"Total SCU: {metrics.total_scu}",
            f"Stops: {metrics.stop_count}",
            f"Reward/Stop: {metrics.reward_per_stop:,.0f} aUEC",
            f"Reward/SCU: {metrics.reward_per_scu:,.1f} aUEC",
            f"Est. Distance: {metrics.estimated_distance:.1f}",
        ]

        for detail in metrics_details:
            detail_item = QTreeWidgetItem(metrics_item)
            detail_item.setText(0, detail)
            items_to_span.append(detail_item)

        # Now set spanning on all items (must be done after items are in tree)
        for span_item in items_to_span:
            span_item.setFirstColumnSpanned(True)

    def refresh(self):
        """Refresh the tab data."""
        self._load_initial_data()
