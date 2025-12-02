"""
Route service for route planning operations.

Handles route optimization and planning using domain models.
"""

from typing import List, Optional
from collections import defaultdict

from src.domain.models import Mission, Route, Stop, Objective
from src.services.vrp_solver import VRPSolver
from src.logger import get_logger

logger = get_logger()


class RouteService:
    """
    Service for route planning and optimization.

    Provides algorithms for creating optimal hauling routes using VRP solver.
    """

    def __init__(self, location_matcher=None, ship_capacity: int = 32):
        """
        Initialize service.

        Args:
            location_matcher: Optional LocationMatcher for normalizing location names
            ship_capacity: Ship cargo capacity in SCU (default: 32 for Freelancer)
        """
        self.location_matcher = location_matcher
        self.ship_capacity = ship_capacity
        self.vrp_solver = VRPSolver(ship_capacity=ship_capacity)

    def create_simple_route(self, missions: List[Mission]) -> Route:
        """
        Create a simple route by ordering missions by reward.

        Args:
            missions: List of missions to include

        Returns:
            Route object
        """
        # Sort by reward (highest first)
        sorted_missions = sorted(missions, key=lambda m: m.reward, reverse=True)

        stops = []
        stop_number = 1
        current_cargo = 0

        # Create stops for each objective
        for mission in sorted_missions:
            for obj in mission.objectives:
                # Pickup stop
                pickup_stop = Stop(
                    location=obj.collect_from,
                    stop_number=stop_number,
                    pickups=[obj],
                    cargo_before=current_cargo,
                    cargo_after=current_cargo + obj.scu_amount
                )
                stops.append(pickup_stop)
                stop_number += 1
                current_cargo += obj.scu_amount

                # Delivery stop
                delivery_stop = Stop(
                    location=obj.deliver_to,
                    stop_number=stop_number,
                    deliveries=[obj],
                    cargo_before=current_cargo,
                    cargo_after=current_cargo - obj.scu_amount
                )
                stops.append(delivery_stop)
                stop_number += 1
                current_cargo -= obj.scu_amount

        route = Route(
            stops=stops,
            total_reward=sum(m.reward for m in missions),
            total_scu=sum(m.total_scu for m in missions),
            mission_count=len(missions)
        )

        logger.info(f"Created simple route with {len(stops)} stops from {len(missions)} missions")
        return route

    def create_grouped_route(self, missions: List[Mission]) -> Route:
        """
        Create route by grouping pickups and deliveries at same locations.

        More efficient than simple route - combines actions at same location.

        Args:
            missions: List of missions to include

        Returns:
            Route object
        """
        # Collect all objectives
        all_objectives = []
        for mission in missions:
            all_objectives.extend(mission.objectives)

        # Group by location
        location_actions = defaultdict(lambda: {"pickups": [], "deliveries": []})

        for obj in all_objectives:
            location_actions[obj.collect_from]["pickups"].append(obj)
            location_actions[obj.deliver_to]["deliveries"].append(obj)

        # Create stops
        stops = []
        current_cargo = 0
        stop_number = 1

        # Simple heuristic: visit each location once
        visited = set()
        for obj in all_objectives:
            # Pickup location
            if obj.collect_from not in visited:
                location = obj.collect_from
                pickups = location_actions[location]["pickups"]
                deliveries = location_actions[location]["deliveries"]

                cargo_before = current_cargo
                # Process deliveries first (unload)
                current_cargo -= sum(d.scu_amount for d in deliveries)
                # Then pickups (load)
                current_cargo += sum(p.scu_amount for p in pickups)

                stop = Stop(
                    location=location,
                    stop_number=stop_number,
                    pickups=pickups,
                    deliveries=deliveries,
                    cargo_before=cargo_before,
                    cargo_after=current_cargo
                )
                stops.append(stop)
                stop_number += 1
                visited.add(location)

            # Delivery location
            if obj.deliver_to not in visited:
                location = obj.deliver_to
                pickups = location_actions[location]["pickups"]
                deliveries = location_actions[location]["deliveries"]

                cargo_before = current_cargo
                # Process deliveries first (unload)
                current_cargo -= sum(d.scu_amount for d in deliveries)
                # Then pickups (load)
                current_cargo += sum(p.scu_amount for p in pickups)

                stop = Stop(
                    location=location,
                    stop_number=stop_number,
                    pickups=pickups,
                    deliveries=deliveries,
                    cargo_before=cargo_before,
                    cargo_after=current_cargo
                )
                stops.append(stop)
                stop_number += 1
                visited.add(location)

        route = Route(
            stops=stops,
            total_reward=sum(m.reward for m in missions),
            total_scu=sum(m.total_scu for m in missions),
            mission_count=len(missions)
        )

        logger.info(f"Created grouped route with {len(stops)} stops from {len(missions)} missions")
        return route

    def optimize_by_reward(self, missions: List[Mission]) -> List[Mission]:
        """
        Sort missions by reward per SCU (most profitable first).

        Args:
            missions: List of missions

        Returns:
            Sorted list of missions
        """
        def reward_per_scu(mission: Mission) -> float:
            if mission.total_scu == 0:
                return 0
            return mission.reward / mission.total_scu

        return sorted(missions, key=reward_per_scu, reverse=True)

    def filter_by_cargo_capacity(
        self,
        missions: List[Mission],
        ship_capacity: int
    ) -> List[Mission]:
        """
        Filter missions that fit within ship capacity.

        Args:
            missions: List of missions
            ship_capacity: Maximum cargo capacity in SCU

        Returns:
            Filtered list of missions
        """
        return [m for m in missions if m.total_scu <= ship_capacity]

    def calculate_max_cargo_load(self, route: Route) -> int:
        """
        Calculate maximum cargo load in a route.

        Args:
            route: Route to analyze

        Returns:
            Maximum SCU at any point
        """
        return route.max_cargo_load

    def validate_route_for_ship(
        self,
        route: Route,
        ship_capacity: int
    ) -> tuple[bool, Optional[str]]:
        """
        Validate if route fits in ship capacity.

        Args:
            route: Route to validate
            ship_capacity: Ship cargo capacity in SCU

        Returns:
            Tuple of (is_valid, error_message)
        """
        max_load = route.max_cargo_load

        if max_load > ship_capacity:
            return False, f"Route requires {max_load} SCU but ship capacity is {ship_capacity} SCU"

        return True, None

    # ========== VRP-Based Methods ==========

    def create_optimized_route(
        self,
        missions: List[Mission],
        starting_location: Optional[str] = None,
        optimization_level: str = 'medium'
    ) -> Route:
        """
        Create an optimized route using VRP solver.

        Uses proper Vehicle Routing Problem algorithms with capacity constraints.

        Args:
            missions: List of missions to route
            starting_location: Optional starting location (current position)
            optimization_level: 'basic', 'medium', or 'advanced'

        Returns:
            Optimized Route object

        Raises:
            ValueError: If route is infeasible due to capacity constraints
        """
        # Update VRP solver with starting location
        self.vrp_solver.starting_location = starting_location

        # Solve VRP
        route = self.vrp_solver.solve(missions, optimization_level=optimization_level)

        logger.info(
            f"Created optimized route with {route.total_stops} stops, "
            f"max load {route.max_cargo_load}/{self.ship_capacity} SCU"
        )

        return route

    def insert_mission_into_route(
        self,
        existing_route: Route,
        new_mission: Mission
    ) -> Route:
        """
        Insert a new mission into an existing route.

        Uses cheapest insertion heuristic to minimize disruption.

        Args:
            existing_route: Current route
            new_mission: Mission to insert

        Returns:
            Updated route with mission inserted

        Raises:
            ValueError: If insertion would violate capacity constraints
        """
        return self.vrp_solver.insert_mission(existing_route, new_mission)

    def validate_missions_feasibility(
        self,
        missions: List[Mission]
    ) -> tuple[bool, Optional[str]]:
        """
        Validate if missions can be completed with current ship capacity.

        Args:
            missions: List of missions to validate

        Returns:
            Tuple of (is_feasible, error_message)
        """
        return self.vrp_solver.validate_missions_feasible(missions)

    def update_ship_capacity(self, new_capacity: int) -> None:
        """
        Update ship capacity (e.g., when switching ships).

        Args:
            new_capacity: New cargo capacity in SCU
        """
        self.ship_capacity = new_capacity
        self.vrp_solver = VRPSolver(ship_capacity=new_capacity)
        logger.info(f"Updated ship capacity to {new_capacity} SCU")

    def get_max_capacity_missions(
        self,
        missions: List[Mission]
    ) -> List[Mission]:
        """
        Select maximum number of missions that fit in ship capacity.

        Uses knapsack-like approach to maximize reward.

        Args:
            missions: Available missions

        Returns:
            Subset of missions that fit in capacity
        """
        # Sort by reward per SCU (most profitable first)
        sorted_missions = self.optimize_by_reward(missions)

        # Greedily select missions that fit
        selected = []
        total_scu = 0

        for mission in sorted_missions:
            # Check if adding this mission would exceed capacity
            if total_scu + mission.total_scu <= self.ship_capacity:
                selected.append(mission)
                total_scu += mission.total_scu

        logger.info(f"Selected {len(selected)}/{len(missions)} missions ({total_scu} SCU)")
        return selected
