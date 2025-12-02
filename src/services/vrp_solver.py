"""
Vehicle Routing Problem solver for hauling missions.

Implements proper VRP algorithms with Pickup and Delivery constraints (VRPPD).
Handles capacity constraints, cargo tracking, and route optimization.
"""

from typing import List, Optional, Dict, Any, Tuple, Set
from dataclasses import dataclass, field
from collections import defaultdict
import math

from src.domain.models import Mission, Route, Stop, Objective
from src.logger import get_logger

logger = get_logger()


@dataclass
class CargoState:
    """Tracks cargo state at a point in the route."""
    current_scu: int = 0
    cargo_items: List[Objective] = field(default_factory=list)

    def can_add(self, scu_amount: int, capacity: int) -> bool:
        """Check if cargo can be added without exceeding capacity."""
        return self.current_scu + scu_amount <= capacity

    def add_cargo(self, objective: Objective) -> None:
        """Add cargo to current state."""
        self.cargo_items.append(objective)
        self.current_scu += objective.scu_amount

    def remove_cargo(self, objective: Objective) -> bool:
        """Remove cargo from current state. Returns True if found and removed."""
        for i, item in enumerate(self.cargo_items):
            if self._objectives_match(item, objective):
                self.cargo_items.pop(i)
                self.current_scu -= objective.scu_amount
                return True
        return False

    @staticmethod
    def _objectives_match(obj1: Objective, obj2: Objective) -> bool:
        """Check if two objectives match (same pickup/delivery/scu)."""
        return (obj1.collect_from == obj2.collect_from and
                obj1.deliver_to == obj2.deliver_to and
                obj1.scu_amount == obj2.scu_amount)

    def copy(self) -> 'CargoState':
        """Create a deep copy of current state."""
        return CargoState(
            current_scu=self.current_scu,
            cargo_items=list(self.cargo_items)
        )


@dataclass
class RouteNode:
    """Represents a node in the route (either pickup or delivery)."""
    location: str
    action_type: str  # 'pickup' or 'delivery'
    objective: Objective
    stop_index: Optional[int] = None

    def __repr__(self) -> str:
        return f"{self.action_type.upper()} at {self.location} ({self.objective.scu_amount} SCU)"


class VRPSolver:
    """
    Vehicle Routing Problem solver with Pickup and Delivery constraints.

    Handles:
    - Capacity constraints
    - Pickup-Delivery precedence (pickup must occur before delivery)
    - Cargo state tracking throughout route
    - Route optimization (nearest neighbor, 2-opt)
    - Route insertion for adding new missions
    """

    def __init__(self, ship_capacity: int, starting_location: Optional[str] = None):
        """
        Initialize VRP solver.

        Args:
            ship_capacity: Maximum cargo capacity in SCU
            starting_location: Optional starting location (e.g., current position)
        """
        self.ship_capacity = ship_capacity
        self.starting_location = starting_location

    def solve(self, missions: List[Mission], optimization_level: str = 'medium') -> Route:
        """
        Solve VRP for given missions.

        Args:
            missions: List of missions to route
            optimization_level: 'basic', 'medium', or 'advanced'

        Returns:
            Optimized route

        Raises:
            ValueError: If route is infeasible (exceeds capacity)
        """
        if not missions:
            return Route(stops=[])

        logger.info(f"Solving VRP for {len(missions)} missions with {self.ship_capacity} SCU capacity")

        # Extract all objectives
        all_objectives = []
        for mission in missions:
            all_objectives.extend(mission.objectives)

        # Build route nodes (pickup and delivery pairs)
        nodes = self._build_route_nodes(all_objectives)

        # Construct initial route using nearest neighbor
        route_sequence = self._nearest_neighbor_construction(nodes)

        # Optimize based on level
        if optimization_level in ['medium', 'advanced']:
            route_sequence = self._optimize_2opt(route_sequence)

        if optimization_level == 'advanced':
            route_sequence = self._optimize_relocate(route_sequence)

        # Build final route with stops
        route = self._build_route_from_sequence(route_sequence, missions)

        # Validate feasibility
        is_valid, error = self._validate_route_feasibility(route)
        if not is_valid:
            logger.error(f"Route validation failed: {error}")
            raise ValueError(f"Infeasible route: {error}")

        logger.info(f"Created route with {route.total_stops} stops, max load {route.max_cargo_load} SCU")
        return route

    def insert_mission(self, existing_route: Route, new_mission: Mission) -> Route:
        """
        Insert a new mission into an existing route with minimal disruption.

        Uses cheapest insertion heuristic to find best position.

        Args:
            existing_route: Current route
            new_mission: Mission to insert

        Returns:
            Updated route with mission inserted

        Raises:
            ValueError: If insertion would violate capacity constraints
        """
        logger.info(f"Inserting mission into route with {existing_route.total_stops} stops")

        # Extract objectives from new mission
        new_objectives = new_mission.objectives

        # Convert existing route to node sequence
        existing_nodes = self._route_to_nodes(existing_route)

        # For each objective, find best insertion position
        best_route = None
        best_cost = float('inf')

        for obj in new_objectives:
            # Create pickup and delivery nodes
            pickup_node = RouteNode(obj.collect_from, 'pickup', obj)
            delivery_node = RouteNode(obj.deliver_to, 'delivery', obj)

            # Try all valid insertion positions
            for pickup_pos in range(len(existing_nodes) + 1):
                for delivery_pos in range(pickup_pos + 1, len(existing_nodes) + 2):
                    # Create candidate route
                    candidate = existing_nodes[:pickup_pos] + [pickup_node] + \
                               existing_nodes[pickup_pos:delivery_pos] + [delivery_node] + \
                               existing_nodes[delivery_pos:]

                    # Check feasibility
                    if self._is_sequence_feasible(candidate):
                        # Calculate insertion cost (additional distance/time)
                        cost = self._calculate_insertion_cost(
                            existing_nodes, candidate, pickup_pos, delivery_pos
                        )

                        if cost < best_cost:
                            best_cost = cost
                            best_route = candidate
                            existing_nodes = candidate  # Update for next objective

        if best_route is None:
            raise ValueError("Cannot insert mission - would violate capacity constraints")

        # Build final route
        all_missions = self._extract_missions_from_route(existing_route) + [new_mission]
        route = self._build_route_from_sequence(best_route, all_missions)

        logger.info(f"Successfully inserted mission, route now has {route.total_stops} stops")
        return route

    def validate_missions_feasible(self, missions: List[Mission]) -> Tuple[bool, Optional[str]]:
        """
        Check if missions can be completed within capacity constraints.

        Only validates if individual objectives are too large for the ship.
        Does NOT validate total route capacity - the VRP solver will handle
        proper sequencing to ensure the ship is never over-full.

        Args:
            missions: List of missions to validate

        Returns:
            Tuple of (is_feasible, error_message)
        """
        # Check if any single objective exceeds capacity
        # This is the only check that matters - if individual objectives fit,
        # the VRP solver will plan a route that respects capacity constraints
        for mission in missions:
            for obj in mission.objectives:
                if obj.scu_amount > self.ship_capacity:
                    error_msg = (
                        f"Single objective requires {obj.scu_amount} SCU but ship capacity "
                        f"is only {self.ship_capacity} SCU.\n\n"
                        f"Objective: {obj.scu_amount} SCU from {obj.collect_from} to {obj.deliver_to}\n\n"
                        f"This objective cannot be completed with the current ship and needs to be "
                        f"removed or split into smaller quantities."
                    )
                    return False, error_msg

        # All objectives fit individually - VRP solver will plan proper sequence
        return True, None

    def _build_route_nodes(self, objectives: List[Objective]) -> List[RouteNode]:
        """Build pickup and delivery nodes from objectives."""
        nodes = []
        for obj in objectives:
            nodes.append(RouteNode(obj.collect_from, 'pickup', obj))
            nodes.append(RouteNode(obj.deliver_to, 'delivery', obj))
        return nodes

    def _nearest_neighbor_construction(self, nodes: List[RouteNode]) -> List[RouteNode]:
        """
        Construct initial route using nearest neighbor heuristic.

        Ensures pickup-delivery precedence and capacity constraints.
        """
        if not nodes:
            return []

        unvisited = set(range(len(nodes)))
        route = []
        cargo_state = CargoState()
        current_location = self.starting_location

        # Group nodes by objective for precedence checking
        objective_to_nodes = defaultdict(list)
        for i, node in enumerate(nodes):
            objective_to_nodes[id(node.objective)].append((i, node))

        while unvisited:
            best_idx = None
            best_distance = float('inf')

            for idx in unvisited:
                node = nodes[idx]

                # Check if this node can be visited
                if not self._can_visit_node(node, route, cargo_state):
                    continue

                # Calculate "distance" (using simple heuristic)
                distance = 0 if current_location is None else \
                          self._location_distance(current_location, node.location)

                # Prefer pickups over deliveries when distance is similar
                if node.action_type == 'pickup':
                    distance *= 0.9

                if distance < best_distance:
                    best_distance = distance
                    best_idx = idx

            if best_idx is None:
                # No feasible node found - route is infeasible
                logger.warning("Nearest neighbor failed to find feasible route")
                break

            # Add node to route
            node = nodes[best_idx]
            route.append(node)
            unvisited.remove(best_idx)

            # Update cargo state
            if node.action_type == 'pickup':
                cargo_state.add_cargo(node.objective)
            else:
                cargo_state.remove_cargo(node.objective)

            current_location = node.location

        return route

    def _can_visit_node(
        self,
        node: RouteNode,
        current_route: List[RouteNode],
        cargo_state: CargoState
    ) -> bool:
        """Check if a node can be visited given current route and cargo state."""
        if node.action_type == 'pickup':
            # Can only pickup if we have capacity
            return cargo_state.can_add(node.objective.scu_amount, self.ship_capacity)
        else:  # delivery
            # Can only deliver if we've already picked up
            for route_node in current_route:
                if (route_node.action_type == 'pickup' and
                    CargoState._objectives_match(route_node.objective, node.objective)):
                    return True
            return False

    def _location_distance(self, loc1: str, loc2: str) -> float:
        """
        Calculate heuristic distance between locations.

        Currently uses simple string comparison. Can be enhanced with actual coordinates.
        """
        if loc1 == loc2:
            return 0.0

        # Simple heuristic: different locations have distance 1.0
        # In future, could use actual coordinates from location database
        return 1.0

    def _optimize_2opt(self, route: List[RouteNode]) -> List[RouteNode]:
        """
        Optimize route using 2-opt algorithm.

        Swaps edges to reduce total distance while maintaining precedence.
        """
        if len(route) <= 3:
            return route

        improved = True
        best_route = route[:]

        while improved:
            improved = False

            for i in range(len(best_route) - 1):
                for j in range(i + 2, len(best_route)):
                    # Try reversing segment [i+1, j]
                    new_route = best_route[:i+1] + best_route[i+1:j+1][::-1] + best_route[j+1:]

                    # Check if new route is feasible
                    if self._is_sequence_feasible(new_route):
                        # Check if it's better
                        if self._calculate_route_cost(new_route) < self._calculate_route_cost(best_route):
                            best_route = new_route
                            improved = True
                            break

                if improved:
                    break

        return best_route

    def _optimize_relocate(self, route: List[RouteNode]) -> List[RouteNode]:
        """
        Optimize by relocating individual nodes.

        Tries moving each node to a better position.
        """
        if len(route) <= 2:
            return route

        improved = True
        best_route = route[:]

        while improved:
            improved = False

            for i in range(len(best_route)):
                node = best_route[i]

                # Try inserting at each position
                for j in range(len(best_route)):
                    if i == j:
                        continue

                    # Create new route with node moved
                    new_route = best_route[:i] + best_route[i+1:]
                    new_route = new_route[:j] + [node] + new_route[j:]

                    # Check feasibility
                    if self._is_sequence_feasible(new_route):
                        if self._calculate_route_cost(new_route) < self._calculate_route_cost(best_route):
                            best_route = new_route
                            improved = True
                            break

                if improved:
                    break

        return best_route

    def _is_sequence_feasible(self, nodes: List[RouteNode]) -> bool:
        """
        Check if node sequence is feasible (precedence + capacity).
        """
        cargo_state = CargoState()
        picked_up = set()

        for node in nodes:
            if node.action_type == 'pickup':
                # Check capacity
                if not cargo_state.can_add(node.objective.scu_amount, self.ship_capacity):
                    return False
                cargo_state.add_cargo(node.objective)
                picked_up.add(id(node.objective))
            else:  # delivery
                # Check if already picked up
                if id(node.objective) not in picked_up:
                    return False
                cargo_state.remove_cargo(node.objective)

        return True

    def _calculate_route_cost(self, nodes: List[RouteNode]) -> float:
        """Calculate total route cost (distance proxy)."""
        if not nodes:
            return 0.0

        cost = 0.0
        prev_location = self.starting_location or nodes[0].location

        for node in nodes:
            cost += self._location_distance(prev_location, node.location)
            prev_location = node.location

        return cost

    def _calculate_insertion_cost(
        self,
        old_route: List[RouteNode],
        new_route: List[RouteNode],
        pickup_pos: int,
        delivery_pos: int
    ) -> float:
        """Calculate cost of inserting nodes into route."""
        return self._calculate_route_cost(new_route) - self._calculate_route_cost(old_route)

    def _build_route_from_sequence(
        self,
        nodes: List[RouteNode],
        missions: List[Mission]
    ) -> Route:
        """
        Build Route object from node sequence.

        Combines actions at same location into single stops.
        """
        if not nodes:
            return Route(
                stops=[],
                starting_location=self.starting_location,
                total_reward=0,
                total_scu=0,
                mission_count=0
            )

        # Group consecutive nodes at same location
        stops = []
        current_location = None
        current_pickups = []
        current_deliveries = []
        cargo_state = CargoState()
        stop_number = 1

        for node in nodes:
            if node.location != current_location and current_location is not None:
                # Create stop for previous location
                cargo_before = cargo_state.copy()

                # Process deliveries first
                for obj in current_deliveries:
                    cargo_state.remove_cargo(obj)

                # Then pickups
                for obj in current_pickups:
                    cargo_state.add_cargo(obj)

                stop = Stop(
                    location=current_location,
                    stop_number=stop_number,
                    pickups=current_pickups[:],
                    deliveries=current_deliveries[:],
                    cargo_before=cargo_before.current_scu,
                    cargo_after=cargo_state.current_scu
                )
                stops.append(stop)
                stop_number += 1

                # Reset for new location
                current_pickups = []
                current_deliveries = []

            current_location = node.location

            if node.action_type == 'pickup':
                current_pickups.append(node.objective)
            else:
                current_deliveries.append(node.objective)

        # Create final stop
        if current_location is not None:
            cargo_before = cargo_state.copy()

            for obj in current_deliveries:
                cargo_state.remove_cargo(obj)
            for obj in current_pickups:
                cargo_state.add_cargo(obj)

            stop = Stop(
                location=current_location,
                stop_number=stop_number,
                pickups=current_pickups,
                deliveries=current_deliveries,
                cargo_before=cargo_before.current_scu,
                cargo_after=cargo_state.current_scu
            )
            stops.append(stop)

        # Calculate totals
        total_reward = sum(m.reward for m in missions)
        total_scu = sum(m.total_scu for m in missions)

        return Route(
            stops=stops,
            starting_location=self.starting_location or (stops[0].location if stops else None),
            total_reward=total_reward,
            total_scu=total_scu,
            mission_count=len(missions)
        )

    def _validate_route_feasibility(self, route: Route) -> Tuple[bool, Optional[str]]:
        """Validate that route doesn't violate capacity constraints."""
        max_load = route.max_cargo_load

        if max_load > self.ship_capacity:
            # Find which stop has the max load
            max_stop = None
            for stop in route.stops:
                if stop.cargo_after == max_load:
                    max_stop = stop
                    break

            error_msg = (
                f"Route planning failed: Peak cargo load ({max_load} SCU) exceeds "
                f"ship capacity ({self.ship_capacity} SCU).\n\n"
            )
            if max_stop:
                error_msg += (
                    f"Maximum load occurs at stop #{max_stop.stop_number}: {max_stop.location}\n"
                    f"After this stop: {max_load} SCU in hold\n\n"
                )
            error_msg += (
                f"This suggests the route optimizer could not find a valid sequence. "
                f"Try using a larger ship or reducing the number of active missions."
            )
            return False, error_msg

        # Validate cargo state consistency
        for stop in route.stops:
            if stop.cargo_before < 0 or stop.cargo_after < 0:
                return False, f"Invalid cargo state at {stop.location}"

        return True, None

    def _route_to_nodes(self, route: Route) -> List[RouteNode]:
        """Convert Route object back to node sequence."""
        nodes = []

        for stop in route.stops:
            # Add pickups first
            for obj in stop.pickups:
                nodes.append(RouteNode(stop.location, 'pickup', obj))
            # Then deliveries
            for obj in stop.deliveries:
                nodes.append(RouteNode(stop.location, 'delivery', obj))

        return nodes

    def _extract_missions_from_route(self, route: Route) -> List[Mission]:
        """Extract missions from a route (best effort reconstruction)."""
        # Group objectives by mission
        all_objectives = []
        for stop in route.stops:
            all_objectives.extend(stop.pickups)

        # This is a simplified version - in practice, missions should be tracked separately
        # For now, return empty list as this is mainly used in insertion
        return []
