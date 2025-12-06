"""
Route Finder Service for querying and optimizing hauling routes.

Provides filtering, route generation, and optimization goal scoring
for finding optimal routes from the mission scan database.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Any, Optional, Set
from itertools import combinations

from src.domain.models import Mission, Objective, Route
from src.services.vrp_solver import VRPSolver
from src.services.location_type_classifier import LocationTypeClassifier, LocationType
from src.location_hierarchy import LocationHierarchy
from src.mission_scan_db import MissionScanDB
from src.ship_profiles import ShipManager, SHIP_PROFILES
from src.logger import get_logger

logger = get_logger()


class OptimizationGoal(Enum):
    """Optimization goals for route finding."""
    MAX_REWARD = "max_reward"
    FEWEST_STOPS = "fewest_stops"
    MIN_DISTANCE = "min_distance"
    BEST_REWARD_PER_STOP = "reward_per_stop"
    BEST_REWARD_PER_SCU = "reward_per_scu"

    @classmethod
    def display_name(cls, goal: 'OptimizationGoal') -> str:
        """Get display name for a goal."""
        names = {
            cls.MAX_REWARD: "Maximum Reward",
            cls.FEWEST_STOPS: "Fewest Stops",
            cls.MIN_DISTANCE: "Minimum Distance",
            cls.BEST_REWARD_PER_STOP: "Best Reward per Stop",
            cls.BEST_REWARD_PER_SCU: "Best Reward per SCU",
        }
        return names.get(goal, str(goal.value))


@dataclass
class OptimizationWeights:
    """Weights for multi-goal optimization (each 0-100)."""
    max_reward: int = 100
    fewest_stops: int = 0
    min_distance: int = 0
    reward_per_stop: int = 0
    reward_per_scu: int = 0

    def is_valid(self) -> bool:
        """Check if at least one weight is non-zero."""
        return any([
            self.max_reward, self.fewest_stops, self.min_distance,
            self.reward_per_stop, self.reward_per_scu
        ])

    def normalized(self) -> Dict[OptimizationGoal, float]:
        """Return weights normalized to sum to 1.0."""
        total = (self.max_reward + self.fewest_stops + self.min_distance +
                 self.reward_per_stop + self.reward_per_scu)
        if total == 0:
            return {OptimizationGoal.MAX_REWARD: 1.0}
        return {
            OptimizationGoal.MAX_REWARD: self.max_reward / total,
            OptimizationGoal.FEWEST_STOPS: self.fewest_stops / total,
            OptimizationGoal.MIN_DISTANCE: self.min_distance / total,
            OptimizationGoal.BEST_REWARD_PER_STOP: self.reward_per_stop / total,
            OptimizationGoal.BEST_REWARD_PER_SCU: self.reward_per_scu / total,
        }

    def get_dominant_goal(self) -> OptimizationGoal:
        """Get the goal with the highest weight (for greedy sorting)."""
        weights = [
            (self.max_reward, OptimizationGoal.MAX_REWARD),
            (self.fewest_stops, OptimizationGoal.FEWEST_STOPS),
            (self.min_distance, OptimizationGoal.MIN_DISTANCE),
            (self.reward_per_stop, OptimizationGoal.BEST_REWARD_PER_STOP),
            (self.reward_per_scu, OptimizationGoal.BEST_REWARD_PER_SCU),
        ]
        return max(weights, key=lambda x: x[0])[1]


class SearchStrategy(Enum):
    """Search strategy for route finding."""
    FAST = "fast"       # Greedy with location affinity
    BETTER = "better"   # Beam search

    @classmethod
    def display_name(cls, strategy: 'SearchStrategy') -> str:
        """Get display name for a strategy."""
        names = {
            cls.FAST: "Fast (Greedy + Affinity)",
            cls.BETTER: "Better (Beam Search)",
        }
        return names.get(strategy, str(strategy.value))


@dataclass
class PartialSolution:
    """A partial solution for beam search."""
    selected_scans: List[Dict[str, Any]]
    locations: Set[str]
    total_reward: float
    total_scu: int
    score: float = 0.0

    def copy(self) -> 'PartialSolution':
        """Create a copy of this solution."""
        return PartialSolution(
            selected_scans=list(self.selected_scans),
            locations=set(self.locations),
            total_reward=self.total_reward,
            total_scu=self.total_scu,
            score=self.score
        )


# Search strategy constants
BEAM_WIDTH = 10
AFFINITY_OVERLAP_BONUS = 0.15  # 15% of reward per shared location
AFFINITY_NEW_PENALTY = 0.05   # 5% of reward per new location


# Optimization presets
OPTIMIZATION_PRESETS: Dict[str, 'OptimizationWeights'] = {
    "Max Profit": None,  # Will be set after class is defined
    "Balanced": None,
    "Efficiency": None,
    "Quick Run": None,
}


def _init_presets():
    """Initialize presets after OptimizationWeights is defined."""
    OPTIMIZATION_PRESETS["Max Profit"] = OptimizationWeights(max_reward=100)
    OPTIMIZATION_PRESETS["Balanced"] = OptimizationWeights(
        max_reward=40, fewest_stops=20, min_distance=20,
        reward_per_stop=10, reward_per_scu=10
    )
    OPTIMIZATION_PRESETS["Efficiency"] = OptimizationWeights(
        max_reward=20, fewest_stops=30, min_distance=0,
        reward_per_stop=30, reward_per_scu=20
    )
    OPTIMIZATION_PRESETS["Quick Run"] = OptimizationWeights(
        max_reward=20, fewest_stops=50, min_distance=30
    )


_init_presets()


# Rank hierarchy (index = level, higher = better)
RANK_HIERARCHY = [
    "Trainee", "Rookie", "Junior", "Member",
    "Experienced", "Senior", "Master"
]


@dataclass
class RouteFinderFilters:
    """Filters for route finding."""
    max_stops: int = 5
    starting_location: Optional[str] = None
    allowed_location_types: List[str] = field(default_factory=lambda: LocationType.all_types())
    allowed_systems: List[str] = field(default_factory=lambda: ["Stanton", "Nyx", "Pyro"])
    min_rank: Optional[str] = None  # Minimum rank (includes this rank and higher)
    min_reward: Optional[float] = None
    max_reward: Optional[float] = None
    ship_key: str = "RSI_ZEUS_MK2_CL"
    round_trip: bool = False

    def get_allowed_ranks(self) -> Optional[List[str]]:
        """Get list of allowed ranks based on min_rank."""
        if not self.min_rank:
            return None  # All ranks allowed

        try:
            min_idx = RANK_HIERARCHY.index(self.min_rank)
            return RANK_HIERARCHY[min_idx:]  # This rank and all higher
        except ValueError:
            return None  # Unknown rank, allow all


@dataclass
class RouteMetrics:
    """Metrics for a candidate route."""
    total_reward: float
    total_scu: int
    stop_count: int
    mission_count: int
    estimated_distance: float
    reward_per_stop: float = 0.0
    reward_per_scu: float = 0.0

    def __post_init__(self):
        """Calculate derived metrics."""
        if self.stop_count > 0:
            self.reward_per_stop = self.total_reward / self.stop_count
        if self.total_scu > 0:
            self.reward_per_scu = self.total_reward / self.total_scu


@dataclass
class CandidateRoute:
    """A candidate route with its missions and metrics."""
    missions: List[Dict[str, Any]]  # Original scan dicts
    route: Route
    score: float
    metrics: RouteMetrics


class RouteFinderService:
    """
    Service for finding optimal routes from mission scans.

    Provides filtering, route generation, and optimization scoring.
    """

    def __init__(
        self,
        scan_db: MissionScanDB,
        location_classifier: LocationTypeClassifier = None,
        location_hierarchy: LocationHierarchy = None,
        ship_manager: ShipManager = None
    ):
        """
        Initialize the route finder service.

        Args:
            scan_db: Mission scan database
            location_classifier: Location type classifier (created if None)
            location_hierarchy: Location hierarchy (created if None)
            ship_manager: Ship manager (created if None)
        """
        self.scan_db = scan_db
        self.classifier = location_classifier or LocationTypeClassifier()
        self.hierarchy = location_hierarchy or LocationHierarchy()
        self.ship_manager = ship_manager or ShipManager()

    def filter_missions(self, filters: RouteFinderFilters) -> List[Dict[str, Any]]:
        """
        Filter mission scans based on criteria.

        Args:
            filters: RouteFinderFilters with criteria

        Returns:
            List of matching scan dicts
        """
        # Get initial scans from DB with basic filters
        allowed_ranks = filters.get_allowed_ranks()
        scans = self.scan_db.query_scans(
            min_reward=filters.min_reward,
            max_reward=filters.max_reward,
            ranks=allowed_ranks
        )

        logger.info(f"Initial query returned {len(scans)} scans")

        # Apply additional filters
        results = []
        for scan in scans:
            if self._scan_matches_filters(scan, filters):
                results.append(scan)

        logger.info(f"After filtering: {len(results)} scans match criteria")
        return results

    def _scan_matches_filters(self, scan: Dict[str, Any], filters: RouteFinderFilters) -> bool:
        """Check if a scan matches all filter criteria."""
        mission_data = scan.get("mission_data", {})
        objectives = mission_data.get("objectives", [])

        if not objectives:
            return False

        # Get ship for capacity check
        ship = self.ship_manager.get_ship(filters.ship_key)
        if not ship:
            ship = SHIP_PROFILES.get(filters.ship_key)

        # Check each objective
        for obj in objectives:
            collect_from = obj.get("collect_from", "")
            deliver_to = obj.get("deliver_to", "")
            scu_amount = obj.get("scu_amount", 0)

            # Check if single objective exceeds ship capacity
            if ship and scu_amount > ship.cargo_capacity_scu:
                return False

            # Check location types
            if filters.allowed_location_types:
                pickup_type = self.classifier.classify_location(collect_from)
                delivery_type = self.classifier.classify_location(deliver_to)

                if pickup_type not in filters.allowed_location_types:
                    return False
                if delivery_type not in filters.allowed_location_types:
                    return False

            # Check systems
            if filters.allowed_systems:
                pickup_system = self.classifier.get_system_for_location(collect_from)
                delivery_system = self.classifier.get_system_for_location(deliver_to)

                # Allow if system is unknown or in allowed list
                if pickup_system and pickup_system not in filters.allowed_systems:
                    return False
                if delivery_system and delivery_system not in filters.allowed_systems:
                    return False

        return True

    def find_best_routes(
        self,
        filters: RouteFinderFilters,
        weights: OptimizationWeights = None,
        max_results: int = 10,
        strategy: SearchStrategy = SearchStrategy.FAST,
        offset: int = 0
    ) -> List[CandidateRoute]:
        """
        Find the best routes matching filters and optimization weights.

        Args:
            filters: RouteFinderFilters with criteria
            weights: OptimizationWeights for multi-goal optimization (defaults to MAX_REWARD only)
            max_results: Maximum number of routes to return
            strategy: SearchStrategy to use (FAST or BETTER)
            offset: Number of routes to skip (for pagination)

        Returns:
            List of CandidateRoute, sorted by score (best first)
        """
        if weights is None:
            weights = OptimizationWeights()  # Defaults to max_reward=100

        # Filter missions
        matching_scans = self.filter_missions(filters)

        if not matching_scans:
            logger.info("No matching missions found")
            return []

        # Build more routes to support pagination
        total_needed = offset + max_results
        candidates = self._build_routes(matching_scans, filters, weights, strategy, total_needed)

        # Apply weighted normalization to recalculate scores
        self._normalize_and_weight_scores(candidates, weights)

        # Sort by weighted score (higher is always better now)
        candidates.sort(key=lambda c: c.score, reverse=True)

        # Return results with offset
        return candidates[offset:offset + max_results]

    def _build_routes(
        self,
        scans: List[Dict[str, Any]],
        filters: RouteFinderFilters,
        weights: OptimizationWeights,
        strategy: SearchStrategy,
        max_routes: int = 10
    ) -> List[CandidateRoute]:
        """
        Build candidate routes from filtered scans.

        Uses different strategies based on strategy parameter and dataset size.
        """
        ship = self.ship_manager.get_ship(filters.ship_key) or SHIP_PROFILES.get(filters.ship_key)
        ship_capacity = ship.cargo_capacity_scu if ship else 128
        goal = weights.get_dominant_goal()

        # Small datasets: always use combinatorial (exhaustive)
        if len(scans) <= 8:
            return self._build_routes_combinatorial(scans, filters, goal, ship_capacity)

        # Larger datasets: use selected strategy
        if strategy == SearchStrategy.FAST:
            return self._build_routes_greedy_affinity(scans, filters, weights, ship_capacity, max_routes)
        elif strategy == SearchStrategy.BETTER:
            return self._build_routes_beam_search(scans, filters, weights, ship_capacity)
        else:
            # Fallback to greedy affinity
            return self._build_routes_greedy_affinity(scans, filters, weights, ship_capacity, max_routes)

    def _build_routes_combinatorial(
        self,
        scans: List[Dict[str, Any]],
        filters: RouteFinderFilters,
        goal: OptimizationGoal,
        ship_capacity: int
    ) -> List[CandidateRoute]:
        """Build routes by enumerating combinations (for small datasets)."""
        candidates = []
        seen_combinations: Set[frozenset] = set()

        # Try different sizes from 1 to max_stops worth of missions
        max_missions = min(len(scans), filters.max_stops)

        for size in range(1, max_missions + 1):
            for combo in combinations(range(len(scans)), size):
                # Create unique key for this combination
                combo_key = frozenset(combo)
                if combo_key in seen_combinations:
                    continue
                seen_combinations.add(combo_key)

                mission_scans = [scans[i] for i in combo]

                # Try to build route
                candidate = self._try_build_route(mission_scans, filters, goal, ship_capacity)
                if candidate:
                    candidates.append(candidate)

        return candidates

    def _build_routes_greedy(
        self,
        scans: List[Dict[str, Any]],
        filters: RouteFinderFilters,
        goal: OptimizationGoal,
        ship_capacity: int
    ) -> List[CandidateRoute]:
        """Build routes using greedy construction (for larger datasets)."""
        candidates = []

        # Sort scans by goal-relevant metric
        sorted_scans = self._sort_scans_by_goal(scans, goal)

        # Build routes incrementally, stopping when we exceed max_stops
        mission_scans = []
        for scan in sorted_scans:
            mission_scans.append(scan)

            # Check if adding more would definitely exceed max_stops
            estimated = self._estimate_stop_count(mission_scans)
            if estimated > filters.max_stops:
                # Remove the last one and stop adding
                mission_scans.pop()
                break

            candidate = self._try_build_route(mission_scans, filters, goal, ship_capacity)
            if candidate:
                candidates.append(candidate)

        # Also try some random samples if dataset is large
        if len(scans) > 15:
            import random
            # Limit sample size based on typical stops per mission
            max_missions = max(1, filters.max_stops // 2)
            for _ in range(20):  # Try 20 random samples
                sample_size = random.randint(1, min(max_missions, len(scans)))
                sample = random.sample(scans, sample_size)
                candidate = self._try_build_route(sample, filters, goal, ship_capacity)
                if candidate:
                    candidates.append(candidate)

        return candidates

    def _build_routes_greedy_affinity(
        self,
        scans: List[Dict[str, Any]],
        filters: RouteFinderFilters,
        weights: OptimizationWeights,
        ship_capacity: int,
        max_routes: int = 10
    ) -> List[CandidateRoute]:
        """
        Build routes using greedy selection with location affinity.

        Tries multiple starting points to find diverse routes.
        Returns up to max_routes unique routes.
        """
        goal = weights.get_dominant_goal()
        candidates = []
        seen_mission_sets: Set[frozenset] = set()

        # Score all scans with base score (by dominant goal)
        scored_scans = []
        for scan in scans:
            base_score = self._get_scan_reward(scan)
            if goal == OptimizationGoal.BEST_REWARD_PER_SCU:
                scu = self._get_scan_scu(scan)
                base_score = base_score / scu if scu > 0 else 0
            scored_scans.append((scan, base_score))

        # Sort by base score descending
        scored_scans.sort(key=lambda x: x[1], reverse=True)

        # Try different starting points to get diverse routes
        num_starts = min(len(scored_scans), max(20, max_routes * 2))

        for start_idx in range(num_starts):
            if len(candidates) >= max_routes:
                break

            candidate = self._greedy_from_start(
                scored_scans, start_idx, filters, weights, goal, ship_capacity
            )

            if candidate:
                # Check if this is a unique mission set
                mission_key = frozenset(id(m) for m in candidate.missions)
                if mission_key not in seen_mission_sets:
                    seen_mission_sets.add(mission_key)
                    candidates.append(candidate)

        return candidates

    def _greedy_from_start(
        self,
        scored_scans: List[tuple],
        start_idx: int,
        filters: RouteFinderFilters,
        weights: OptimizationWeights,
        goal: OptimizationGoal,
        ship_capacity: int
    ) -> Optional[CandidateRoute]:
        """Build one route starting from a specific mission index."""
        best_candidate = None
        selected_scans = []
        selected_locations: Set[str] = set()

        # Start with the specified mission
        start_scan, _ = scored_scans[start_idx]
        selected_scans.append(start_scan)
        selected_locations = self._get_scan_locations(start_scan)

        # Build available list excluding the start
        available = [(s, score) for i, (s, score) in enumerate(scored_scans) if i != start_idx]

        while available:
            # Stop if we've hit the location limit
            if len(selected_locations) >= filters.max_stops:
                break

            # Stop if best candidate already at max stops
            if best_candidate and best_candidate.route.total_stops >= filters.max_stops:
                break

            best_scan = None
            best_combined_score = float('-inf')

            for scan, base_score in available:
                scan_locs = self._get_scan_locations(scan)
                potential_locs = selected_locations | scan_locs

                # Skip if would exceed max_stops
                if len(potential_locs) > filters.max_stops:
                    continue

                # Calculate combined score with affinity
                affinity = self._calculate_affinity_score(scan, selected_locations, weights)
                combined = base_score + affinity

                if combined > best_combined_score:
                    best_combined_score = combined
                    best_scan = scan

            if best_scan is None:
                break

            selected_scans.append(best_scan)
            selected_locations |= self._get_scan_locations(best_scan)
            available = [(s, score) for s, score in available if s is not best_scan]

            candidate = self._try_build_route(selected_scans, filters, goal, ship_capacity)
            if candidate:
                if best_candidate is None or candidate.metrics.total_reward > best_candidate.metrics.total_reward:
                    best_candidate = candidate
            elif best_candidate:
                break

        return best_candidate

    def _build_routes_beam_search(
        self,
        scans: List[Dict[str, Any]],
        filters: RouteFinderFilters,
        weights: OptimizationWeights,
        ship_capacity: int
    ) -> List[CandidateRoute]:
        """
        Build routes using beam search.

        Maintains top K partial solutions at each step, exploring multiple
        paths to find better route combinations.
        """
        goal = weights.get_dominant_goal()

        # Initialize beam with empty solution
        beam: List[PartialSolution] = [
            PartialSolution(
                selected_scans=[],
                locations=set(),
                total_reward=0,
                total_scu=0,
                score=0
            )
        ]

        # Pre-compute scan data
        scan_data = []
        for scan in scans:
            scan_data.append({
                'scan': scan,
                'locations': self._get_scan_locations(scan),
                'reward': self._get_scan_reward(scan),
                'scu': self._get_scan_scu(scan),
            })

        # Iterate beam search
        iterations = 0
        max_iterations = min(len(scans), filters.max_stops * 2)

        while iterations < max_iterations:
            iterations += 1
            next_beam: List[PartialSolution] = []

            for partial in beam:
                # Track which scans are already selected (by index)
                selected_indices = set()
                for sel_scan in partial.selected_scans:
                    for i, sd in enumerate(scan_data):
                        if sd['scan'] is sel_scan:
                            selected_indices.add(i)
                            break

                # Try adding each remaining scan
                for i, sd in enumerate(scan_data):
                    if i in selected_indices:
                        continue

                    # Check if adding would exceed max_stops
                    new_locs = partial.locations | sd['locations']
                    if len(new_locs) > filters.max_stops:
                        continue

                    # Create new partial solution
                    new_partial = partial.copy()
                    new_partial.selected_scans.append(sd['scan'])
                    new_partial.locations = new_locs
                    new_partial.total_reward += sd['reward']
                    new_partial.total_scu += sd['scu']
                    new_partial.score = self._score_partial_solution(new_partial, weights)

                    next_beam.append(new_partial)

            if not next_beam:
                break  # No more expansions possible

            # Keep top K solutions (beam width)
            next_beam.sort(key=lambda p: p.score, reverse=True)
            beam = next_beam[:BEAM_WIDTH]

        # Build actual routes from final beam solutions
        candidates = []
        seen_keys: Set[frozenset] = set()

        for partial in beam:
            if not partial.selected_scans:
                continue

            # Dedup by scan set
            key = frozenset(id(s) for s in partial.selected_scans)
            if key in seen_keys:
                continue
            seen_keys.add(key)

            # Try to build actual route
            candidate = self._try_build_route(
                partial.selected_scans, filters, goal, ship_capacity
            )
            if candidate:
                candidates.append(candidate)

        return candidates

    def _sort_scans_by_goal(
        self,
        scans: List[Dict[str, Any]],
        goal: OptimizationGoal
    ) -> List[Dict[str, Any]]:
        """Sort scans by goal-relevant metric."""
        def get_reward(s):
            return s.get("mission_data", {}).get("reward", 0)

        def get_scu(s):
            objs = s.get("mission_data", {}).get("objectives", [])
            return sum(o.get("scu_amount", 0) for o in objs)

        def get_reward_per_scu(s):
            reward = get_reward(s)
            scu = get_scu(s)
            return reward / scu if scu > 0 else 0

        if goal == OptimizationGoal.MAX_REWARD:
            return sorted(scans, key=get_reward, reverse=True)
        elif goal == OptimizationGoal.BEST_REWARD_PER_SCU:
            return sorted(scans, key=get_reward_per_scu, reverse=True)
        elif goal == OptimizationGoal.FEWEST_STOPS:
            # Prefer missions with higher reward (to maximize value with fewer stops)
            return sorted(scans, key=get_reward, reverse=True)
        else:
            # Default: by reward
            return sorted(scans, key=get_reward, reverse=True)

    def _estimate_stop_count(self, mission_scans: List[Dict[str, Any]]) -> int:
        """Estimate minimum stops for a set of missions (before VRP solving)."""
        # Collect all unique locations
        locations = set()
        for scan in mission_scans:
            for obj in scan.get("mission_data", {}).get("objectives", []):
                locations.add(obj.get("collect_from", ""))
                locations.add(obj.get("deliver_to", ""))
        locations.discard("")
        return len(locations)

    def _get_scan_locations(self, scan: Dict[str, Any]) -> Set[str]:
        """Extract all unique locations from a scan."""
        locations = set()
        for obj in scan.get("mission_data", {}).get("objectives", []):
            collect = obj.get("collect_from", "")
            deliver = obj.get("deliver_to", "")
            if collect:
                locations.add(collect)
            if deliver:
                locations.add(deliver)
        return locations

    def _get_scan_reward(self, scan: Dict[str, Any]) -> float:
        """Get total reward from a scan."""
        return scan.get("mission_data", {}).get("reward", 0)

    def _get_scan_scu(self, scan: Dict[str, Any]) -> int:
        """Get total SCU from a scan."""
        objs = scan.get("mission_data", {}).get("objectives", [])
        return sum(o.get("scu_amount", 0) for o in objs)

    def _calculate_affinity_score(
        self,
        scan: Dict[str, Any],
        selected_locations: Set[str],
        weights: OptimizationWeights
    ) -> float:
        """
        Calculate affinity bonus for a scan based on location overlap.

        Returns a bonus that rewards sharing locations with already-selected missions.
        """
        if not selected_locations:
            return 0.0  # First mission, no affinity

        scan_locations = self._get_scan_locations(scan)
        base_reward = self._get_scan_reward(scan)

        # Count overlapping and new locations
        overlap_count = len(scan_locations & selected_locations)
        new_count = len(scan_locations - selected_locations)

        # Scale by fewest_stops weight (higher = stronger affinity preference)
        stop_weight = max(0.1, weights.fewest_stops / 100.0)

        affinity = (
            overlap_count * base_reward * AFFINITY_OVERLAP_BONUS * stop_weight -
            new_count * base_reward * AFFINITY_NEW_PENALTY * stop_weight
        )

        return affinity

    def _score_partial_solution(
        self,
        partial: PartialSolution,
        weights: OptimizationWeights
    ) -> float:
        """
        Score a partial solution for beam search ranking.

        Uses similar logic to final scoring but works on estimated data.
        """
        norm_weights = weights.normalized()
        estimated_stops = len(partial.locations)

        if estimated_stops == 0 or partial.total_reward == 0:
            return 0.0

        # Calculate component scores
        scores = {
            OptimizationGoal.MAX_REWARD: partial.total_reward,
            OptimizationGoal.FEWEST_STOPS: partial.total_reward / (estimated_stops ** 1.5),
            OptimizationGoal.MIN_DISTANCE: partial.total_reward / (estimated_stops ** 1.5),
            OptimizationGoal.BEST_REWARD_PER_STOP: partial.total_reward / estimated_stops,
            OptimizationGoal.BEST_REWARD_PER_SCU: (
                partial.total_reward / partial.total_scu if partial.total_scu > 0 else 0
            ),
        }

        # Weighted sum
        return sum(scores.get(goal, 0) * w for goal, w in norm_weights.items())

    def _try_build_route(
        self,
        mission_scans: List[Dict[str, Any]],
        filters: RouteFinderFilters,
        goal: OptimizationGoal,
        ship_capacity: int
    ) -> Optional[CandidateRoute]:
        """Try to build a route from mission scans, return None if infeasible."""
        try:
            # Quick check: estimate stops before expensive VRP solving
            estimated_stops = self._estimate_stop_count(mission_scans)
            if estimated_stops > filters.max_stops:
                return None

            # Convert scans to Mission objects
            missions = []
            for scan in mission_scans:
                mission = self._scan_to_mission(scan)
                if mission:
                    missions.append(mission)

            if not missions:
                return None

            # Use VRP solver
            solver = VRPSolver(
                ship_capacity=ship_capacity,
                starting_location=filters.starting_location
            )

            # Check feasibility first
            is_feasible, error = solver.validate_missions_feasible(missions)
            if not is_feasible:
                return None

            # Solve route with max_stops limit (returns None if exceeded)
            route = solver.solve(
                missions,
                optimization_level='medium',
                max_stops=filters.max_stops
            )

            if route is None:
                return None

            # Check actual stop count (can exceed unique locations due to revisits)
            if route.total_stops > filters.max_stops:
                return None

            # Handle round trip
            if filters.round_trip and route.stops:
                # Add return distance to metrics
                pass  # Route distance will include return

            # Calculate metrics
            metrics = self._calculate_metrics(route, missions)

            # Calculate score
            score = self._calculate_score(metrics, goal)

            return CandidateRoute(
                missions=mission_scans,
                route=route,
                score=score,
                metrics=metrics
            )

        except Exception as e:
            logger.debug(f"Failed to build route: {e}")
            return None

    def _scan_to_mission(self, scan: Dict[str, Any]) -> Optional[Mission]:
        """Convert a scan dict to a Mission object."""
        try:
            mission_data = scan.get("mission_data", {})

            objectives = []
            for obj_data in mission_data.get("objectives", []):
                obj = Objective(
                    collect_from=obj_data.get("collect_from", "Unknown"),
                    deliver_to=obj_data.get("deliver_to", "Unknown"),
                    scu_amount=obj_data.get("scu_amount", 1),
                    cargo_type=obj_data.get("cargo_type", "Unknown")
                )
                objectives.append(obj)

            if not objectives:
                return None

            reward = mission_data.get("reward", 0)
            if reward <= 0:
                reward = 1  # Avoid validation error

            mission = Mission(
                reward=reward,
                availability=mission_data.get("availability", "N/A"),
                objectives=objectives
            )
            return mission

        except Exception as e:
            logger.debug(f"Failed to convert scan to mission: {e}")
            return None

    def _calculate_metrics(self, route: Route, missions: List[Mission]) -> RouteMetrics:
        """Calculate route metrics."""
        # Get all locations in order
        locations = [stop.location for stop in route.stops]

        # Estimate distance
        estimated_distance = self.hierarchy.estimate_route_distance(locations)

        return RouteMetrics(
            total_reward=route.total_reward,
            total_scu=route.total_scu,
            stop_count=route.total_stops,
            mission_count=len(missions),
            estimated_distance=estimated_distance
        )

    def _calculate_raw_scores(self, metrics: RouteMetrics) -> Dict[OptimizationGoal, float]:
        """Calculate raw scores for all optimization goals."""
        scores = {}

        # MAX_REWARD: higher is better
        scores[OptimizationGoal.MAX_REWARD] = metrics.total_reward

        # FEWEST_STOPS: lower stops is better -> use reward/stops^1.5
        if metrics.stop_count > 0:
            scores[OptimizationGoal.FEWEST_STOPS] = metrics.total_reward / (metrics.stop_count ** 1.5)
        else:
            scores[OptimizationGoal.FEWEST_STOPS] = 0

        # MIN_DISTANCE: lower distance is better -> use reward/distance^1.5
        if metrics.estimated_distance > 0:
            scores[OptimizationGoal.MIN_DISTANCE] = metrics.total_reward / (metrics.estimated_distance ** 1.5)
        else:
            scores[OptimizationGoal.MIN_DISTANCE] = metrics.total_reward

        # REWARD_PER_STOP: higher is better
        scores[OptimizationGoal.BEST_REWARD_PER_STOP] = metrics.reward_per_stop

        # REWARD_PER_SCU: higher is better
        scores[OptimizationGoal.BEST_REWARD_PER_SCU] = metrics.reward_per_scu

        return scores

    def _calculate_score(self, metrics: RouteMetrics, goal: OptimizationGoal) -> float:
        """Calculate score for a route based on optimization goal."""
        if goal == OptimizationGoal.MAX_REWARD:
            return metrics.total_reward

        elif goal == OptimizationGoal.FEWEST_STOPS:
            # Lower is better, but we want high reward too
            # Score = reward / (stops^2) to heavily penalize more stops
            if metrics.stop_count > 0:
                return metrics.total_reward / (metrics.stop_count ** 1.5)
            return 0

        elif goal == OptimizationGoal.MIN_DISTANCE:
            # Lower distance is better, but reward matters too
            # Score = reward / (distance^1.5)
            if metrics.estimated_distance > 0:
                return metrics.total_reward / (metrics.estimated_distance ** 1.5)
            return metrics.total_reward

        elif goal == OptimizationGoal.BEST_REWARD_PER_STOP:
            return metrics.reward_per_stop

        elif goal == OptimizationGoal.BEST_REWARD_PER_SCU:
            return metrics.reward_per_scu

        return 0

    def _normalize_and_weight_scores(
        self,
        candidates: List[CandidateRoute],
        weights: OptimizationWeights
    ) -> None:
        """
        Normalize scores across candidates and apply weights.

        Uses min-max normalization to ensure each goal contributes proportionally,
        regardless of different score magnitudes.
        """
        if not candidates:
            return

        norm_weights = weights.normalized()

        # Collect raw scores per goal for all candidates
        all_raw_scores: Dict[OptimizationGoal, List[float]] = {
            goal: [] for goal in OptimizationGoal
        }

        for candidate in candidates:
            goal_scores = self._calculate_raw_scores(candidate.metrics)
            for goal, score in goal_scores.items():
                all_raw_scores[goal].append(score)

        # Calculate min/max per goal for normalization
        min_max: Dict[OptimizationGoal, tuple] = {}
        for goal in OptimizationGoal:
            scores = all_raw_scores[goal]
            min_val = min(scores) if scores else 0
            max_val = max(scores) if scores else 0
            min_max[goal] = (min_val, max_val)

        # Normalize and weight each candidate's score
        for candidate in candidates:
            weighted_score = 0.0
            goal_scores = self._calculate_raw_scores(candidate.metrics)

            for goal, raw in goal_scores.items():
                min_val, max_val = min_max[goal]

                # Normalize to [0, 1] range
                if max_val > min_val:
                    normalized = (raw - min_val) / (max_val - min_val)
                else:
                    normalized = 1.0  # All candidates have same value

                # Apply weight
                weighted_score += normalized * norm_weights.get(goal, 0)

            candidate.score = weighted_score

    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics about available missions."""
        scans = self.scan_db.get_scans()

        if not scans:
            return {
                "total_missions": 0,
                "total_reward": 0,
                "unique_locations": 0,
                "systems": {}
            }

        total_reward = 0
        locations = set()
        systems: Dict[str, int] = {}

        for scan in scans:
            mission_data = scan.get("mission_data", {})
            total_reward += mission_data.get("reward", 0)

            for obj in mission_data.get("objectives", []):
                collect_from = obj.get("collect_from", "")
                deliver_to = obj.get("deliver_to", "")

                if collect_from:
                    locations.add(collect_from)
                    system = self.classifier.get_system_for_location(collect_from)
                    if system:
                        systems[system] = systems.get(system, 0) + 1

                if deliver_to:
                    locations.add(deliver_to)
                    system = self.classifier.get_system_for_location(deliver_to)
                    if system:
                        systems[system] = systems.get(system, 0) + 1

        return {
            "total_missions": len(scans),
            "total_reward": total_reward,
            "unique_locations": len(locations),
            "systems": systems
        }
