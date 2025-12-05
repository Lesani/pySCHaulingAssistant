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
        goal: OptimizationGoal,
        max_results: int = 10
    ) -> List[CandidateRoute]:
        """
        Find the best routes matching filters and optimization goal.

        Args:
            filters: RouteFinderFilters with criteria
            goal: OptimizationGoal to optimize for
            max_results: Maximum number of routes to return

        Returns:
            List of CandidateRoute, sorted by score (best first)
        """
        # Filter missions
        matching_scans = self.filter_missions(filters)

        if not matching_scans:
            logger.info("No matching missions found")
            return []

        # Build routes
        candidates = self._build_routes(matching_scans, filters, goal)

        # Sort by score (descending for most goals)
        reverse = goal not in [OptimizationGoal.FEWEST_STOPS, OptimizationGoal.MIN_DISTANCE]
        candidates.sort(key=lambda c: c.score, reverse=reverse)

        # Return top results
        return candidates[:max_results]

    def _build_routes(
        self,
        scans: List[Dict[str, Any]],
        filters: RouteFinderFilters,
        goal: OptimizationGoal
    ) -> List[CandidateRoute]:
        """
        Build candidate routes from filtered scans.

        Uses different strategies based on dataset size.
        """
        candidates = []
        ship = self.ship_manager.get_ship(filters.ship_key) or SHIP_PROFILES.get(filters.ship_key)
        ship_capacity = ship.cargo_capacity_scu if ship else 128

        # Determine strategy based on scan count
        if len(scans) <= 8:
            # Small set: enumerate combinations
            candidates = self._build_routes_combinatorial(scans, filters, goal, ship_capacity)
        else:
            # Larger set: greedy construction
            candidates = self._build_routes_greedy(scans, filters, goal, ship_capacity)

        return candidates

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

        # Build routes of increasing size
        for end_idx in range(1, min(len(sorted_scans) + 1, filters.max_stops * 2)):
            mission_scans = sorted_scans[:end_idx]

            candidate = self._try_build_route(mission_scans, filters, goal, ship_capacity)
            if candidate:
                candidates.append(candidate)

        # Also try some random samples if dataset is large
        if len(scans) > 15:
            import random
            for _ in range(20):  # Try 20 random samples
                sample_size = random.randint(1, min(filters.max_stops, len(scans)))
                sample = random.sample(scans, sample_size)
                candidate = self._try_build_route(sample, filters, goal, ship_capacity)
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

    def _try_build_route(
        self,
        mission_scans: List[Dict[str, Any]],
        filters: RouteFinderFilters,
        goal: OptimizationGoal,
        ship_capacity: int
    ) -> Optional[CandidateRoute]:
        """Try to build a route from mission scans, return None if infeasible."""
        try:
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

            # Solve route
            route = solver.solve(missions, optimization_level='medium')

            # Check max stops constraint
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
