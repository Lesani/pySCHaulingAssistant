"""
Route planning for hauling missions with pickup/delivery constraints.

Implements proper route planning algorithms that generate a sequence of stops,
tracking cargo state throughout the route.
"""

from typing import List, Dict, Any, Set, Tuple
from dataclasses import dataclass


@dataclass
class Objective:
    """Represents a single cargo objective."""
    mission_id: str
    collect_from: str
    deliver_to: str
    scu_amount: int
    reward: int


@dataclass
class Stop:
    """Represents a single stop in the route."""
    stop_number: int
    location: str
    pickups: List[Objective]
    deliveries: List[Objective]
    cargo_before: int
    cargo_after: int


class RoutePlanner:
    """Plans efficient routes for hauling missions."""

    def __init__(self, proximity_calculator=None):
        """
        Initialize route planner.

        Args:
            proximity_calculator: Optional LocationProximity instance for distance calculations
        """
        self.proximity = proximity_calculator

    def extract_objectives(self, missions: List[Dict[str, Any]]) -> List[Objective]:
        """Extract all objectives from missions into flat list."""
        objectives = []
        for mission in missions:
            for obj in mission.get("objectives", []):
                objectives.append(Objective(
                    mission_id=mission.get("id"),
                    collect_from=obj.get("collect_from", "Unknown"),
                    deliver_to=obj.get("deliver_to", "Unknown"),
                    scu_amount=obj.get("scu_amount", 0),
                    reward=mission.get("reward", 0)
                ))
        return objectives

    def build_lifo_route(self, missions: List[Dict[str, Any]], start_location: str) -> List[Stop]:
        """
        Build LIFO (Last In First Out) route using greedy delivery-first algorithm.

        Strategy:
        1. Start at starting location, pick up all available cargo
        2. Always prioritize delivering cargo we're carrying (LIFO - deliver ASAP)
        3. When cargo hold is empty, pick up from nearest available location
        4. Repeat until all objectives complete

        Args:
            missions: List of mission dictionaries
            start_location: Starting location name

        Returns:
            List of Stop objects representing the route
        """
        objectives = self.extract_objectives(missions)
        if not objectives:
            return []

        stops = []
        cargo_hold: List[Objective] = []  # Currently carrying
        pending: List[Objective] = objectives.copy()
        completed: Set[Tuple[str, str, int]] = set()  # Track completed objectives
        current_location = start_location
        stop_number = 0

        # First stop: pick up everything at start location
        pickups_here = [obj for obj in pending if obj.collect_from == current_location]
        if pickups_here:
            stop_number += 1
            for obj in pickups_here:
                cargo_hold.append(obj)
                pending.remove(obj)

            stops.append(Stop(
                stop_number=stop_number,
                location=current_location,
                pickups=pickups_here,
                deliveries=[],
                cargo_before=0,
                cargo_after=sum(obj.scu_amount for obj in cargo_hold)
            ))

        # Continue until all cargo delivered and all pickups done
        while cargo_hold or pending:
            cargo_before = sum(obj.scu_amount for obj in cargo_hold)

            # Priority 1: Deliver cargo we're carrying
            if cargo_hold:
                # Find nearest delivery location for cargo we're carrying
                delivery_locations = set(obj.deliver_to for obj in cargo_hold)
                next_location = self._find_nearest_location(current_location, delivery_locations)

                # Deliver and pick up at this location
                deliveries_here = [obj for obj in cargo_hold if obj.deliver_to == next_location]
                pickups_here = [obj for obj in pending if obj.collect_from == next_location]

                # Update cargo hold
                for obj in deliveries_here:
                    cargo_hold.remove(obj)
                    completed.add((obj.collect_from, obj.deliver_to, obj.scu_amount))

                for obj in pickups_here:
                    cargo_hold.append(obj)
                    pending.remove(obj)

                cargo_after = sum(obj.scu_amount for obj in cargo_hold)

                stop_number += 1
                stops.append(Stop(
                    stop_number=stop_number,
                    location=next_location,
                    pickups=pickups_here,
                    deliveries=deliveries_here,
                    cargo_before=cargo_before,
                    cargo_after=cargo_after
                ))
                current_location = next_location

            # Priority 2: Pick up more cargo (when hold is empty)
            elif pending:
                pickup_locations = set(obj.collect_from for obj in pending)
                next_location = self._find_nearest_location(current_location, pickup_locations)

                pickups_here = [obj for obj in pending if obj.collect_from == next_location]

                for obj in pickups_here:
                    cargo_hold.append(obj)
                    pending.remove(obj)

                cargo_after = sum(obj.scu_amount for obj in cargo_hold)

                stop_number += 1
                stops.append(Stop(
                    stop_number=stop_number,
                    location=next_location,
                    pickups=pickups_here,
                    deliveries=[],
                    cargo_before=0,
                    cargo_after=cargo_after
                ))
                current_location = next_location

        return stops

    def build_proximity_route(self, missions: List[Dict[str, Any]], start_location: str) -> List[Stop]:
        """
        Build proximity-based route using nearest neighbor algorithm.

        Strategy:
        1. Start at starting location
        2. Always visit nearest unvisited location
        3. Pick up and deliver at each stop as available

        Args:
            missions: List of mission dictionaries
            start_location: Starting location name

        Returns:
            List of Stop objects representing the route
        """
        objectives = self.extract_objectives(missions)
        if not objectives:
            return []

        # Get all unique locations
        all_locations = set()
        for obj in objectives:
            all_locations.add(obj.collect_from)
            all_locations.add(obj.deliver_to)

        stops = []
        cargo_hold: List[Objective] = []
        pending: List[Objective] = objectives.copy()
        visited: Set[str] = set()
        current_location = start_location
        stop_number = 0

        # Visit all locations in proximity order
        while len(visited) < len(all_locations):
            cargo_before = sum(obj.scu_amount for obj in cargo_hold)

            # Pick up and deliver at current location
            pickups_here = [obj for obj in pending if obj.collect_from == current_location]
            deliveries_here = [obj for obj in cargo_hold if obj.deliver_to == current_location]

            # Only create stop if there's activity here
            if pickups_here or deliveries_here:
                for obj in deliveries_here:
                    cargo_hold.remove(obj)

                for obj in pickups_here:
                    cargo_hold.append(obj)
                    pending.remove(obj)

                cargo_after = sum(obj.scu_amount for obj in cargo_hold)

                stop_number += 1
                stops.append(Stop(
                    stop_number=stop_number,
                    location=current_location,
                    pickups=pickups_here,
                    deliveries=deliveries_here,
                    cargo_before=cargo_before,
                    cargo_after=cargo_after
                ))

            visited.add(current_location)

            # Find nearest unvisited location
            unvisited = all_locations - visited
            if unvisited:
                current_location = self._find_nearest_location(current_location, unvisited)
            else:
                break

        # If there's still cargo in hold, deliver it
        while cargo_hold:
            cargo_before = sum(obj.scu_amount for obj in cargo_hold)

            # Find nearest delivery location
            delivery_locations = set(obj.deliver_to for obj in cargo_hold)
            next_location = self._find_nearest_location(current_location, delivery_locations)

            deliveries_here = [obj for obj in cargo_hold if obj.deliver_to == next_location]

            for obj in deliveries_here:
                cargo_hold.remove(obj)

            stop_number += 1
            stops.append(Stop(
                stop_number=stop_number,
                location=next_location,
                pickups=[],
                deliveries=deliveries_here,
                cargo_before=cargo_before,
                cargo_after=0
            ))
            current_location = next_location

        return stops

    def _find_nearest_location(self, current: str, candidates: Set[str]) -> str:
        """
        Find nearest location from candidates.

        Args:
            current: Current location
            candidates: Set of candidate locations

        Returns:
            Nearest location name
        """
        if not candidates:
            return current

        if len(candidates) == 1:
            return list(candidates)[0]

        # Use proximity calculator if available
        if self.proximity:
            sorted_candidates = self.proximity.sort_locations_by_proximity(
                list(candidates), current
            )
            return sorted_candidates[0]

        # Fallback: alphabetical
        return sorted(candidates)[0]
