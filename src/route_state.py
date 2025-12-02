"""
Route state tracking for incremental route planning.

Tracks completed stops and current cargo state for resume functionality.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Set, Optional
from datetime import datetime

from src.domain.models import Stop, Mission, Objective
from src.logger import get_logger

logger = get_logger()


@dataclass
class CargoState:
    """
    Current cargo hold state.

    Tracks what cargo is currently loaded.
    """
    loaded_objectives: List[Objective] = field(default_factory=list)
    current_scu: int = 0

    def add_cargo(self, objective: Objective) -> None:
        """Add cargo to hold."""
        self.loaded_objectives.append(objective)
        self.current_scu += objective.scu_amount
        logger.debug(f"Added {objective.scu_amount} SCU, total now: {self.current_scu}")

    def remove_cargo(self, objective: Objective) -> bool:
        """
        Remove cargo from hold.

        Returns True if removed, False if not found.
        """
        for i, obj in enumerate(self.loaded_objectives):
            if (obj.collect_from == objective.collect_from and
                obj.deliver_to == objective.deliver_to and
                obj.scu_amount == objective.scu_amount):
                self.loaded_objectives.pop(i)
                self.current_scu -= objective.scu_amount
                logger.debug(f"Removed {objective.scu_amount} SCU, total now: {self.current_scu}")
                return True
        return False

    def get_cargo_for_destination(self, destination: str) -> List[Objective]:
        """Get all cargo destined for a specific location."""
        return [obj for obj in self.loaded_objectives if obj.deliver_to == destination]

    def clear(self) -> None:
        """Clear all cargo."""
        self.loaded_objectives.clear()
        self.current_scu = 0


@dataclass
class RouteState:
    """
    Tracks progress through a hauling route.

    Maintains state of completed stops, current location, and cargo.
    """
    completed_stop_ids: Set[str] = field(default_factory=set)
    current_location: Optional[str] = None
    cargo_state: CargoState = field(default_factory=CargoState)
    last_update: str = field(default_factory=lambda: datetime.now().isoformat())

    def mark_stop_completed(self, stop: Stop) -> None:
        """
        Mark a stop as completed and update cargo state.

        Args:
            stop: Stop that was completed
        """
        # Generate unique stop ID
        stop_id = f"{stop.location}_{stop.stop_number}"

        if stop_id in self.completed_stop_ids:
            logger.warning(f"Stop {stop_id} already marked as completed")
            return

        # Process deliveries (unload cargo)
        for delivery in stop.deliveries:
            self.cargo_state.remove_cargo(delivery)

        # Process pickups (load cargo)
        for pickup in stop.pickups:
            self.cargo_state.add_cargo(pickup)

        # Mark as completed
        self.completed_stop_ids.add(stop_id)
        self.current_location = stop.location
        self.last_update = datetime.now().isoformat()

        logger.info(f"Completed stop at {stop.location}, cargo: {self.cargo_state.current_scu} SCU")

    def unmark_stop(self, stop: Stop) -> None:
        """
        Unmark a stop as completed (undo).

        Args:
            stop: Stop to unmark
        """
        stop_id = f"{stop.location}_{stop.stop_number}"

        if stop_id not in self.completed_stop_ids:
            logger.warning(f"Stop {stop_id} was not marked as completed")
            return

        # Reverse the cargo operations (in opposite order)
        # Remove pickups (unload what was loaded)
        for pickup in stop.pickups:
            self.cargo_state.remove_cargo(pickup)

        # Add back deliveries (reload what was delivered)
        for delivery in stop.deliveries:
            self.cargo_state.add_cargo(delivery)

        # Unmark
        self.completed_stop_ids.remove(stop_id)
        self.last_update = datetime.now().isoformat()

        logger.info(f"Unmarked stop at {stop.location}")

    def is_stop_completed(self, stop: Stop) -> bool:
        """Check if a stop is completed."""
        stop_id = f"{stop.location}_{stop.stop_number}"
        return stop_id in self.completed_stop_ids

    def get_remaining_objectives(self, all_objectives: List[Objective]) -> List[Objective]:
        """
        Get objectives that haven't been picked up yet.

        Args:
            all_objectives: All objectives from missions

        Returns:
            List of objectives not yet in cargo or delivered
        """
        remaining = []
        loaded_set = {(obj.collect_from, obj.deliver_to, obj.scu_amount)
                      for obj in self.cargo_state.loaded_objectives}

        for obj in all_objectives:
            obj_tuple = (obj.collect_from, obj.deliver_to, obj.scu_amount)
            if obj_tuple not in loaded_set:
                remaining.append(obj)

        return remaining

    def get_pending_deliveries(self) -> List[Objective]:
        """Get all cargo currently loaded (pending delivery)."""
        return self.cargo_state.loaded_objectives.copy()

    def reset(self) -> None:
        """Reset route state to beginning."""
        self.completed_stop_ids.clear()
        self.current_location = None
        self.cargo_state.clear()
        self.last_update = datetime.now().isoformat()
        logger.info("Route state reset")

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "completed_stop_ids": list(self.completed_stop_ids),
            "current_location": self.current_location,
            "current_scu": self.cargo_state.current_scu,
            "loaded_objectives": [obj.to_dict() for obj in self.cargo_state.loaded_objectives],
            "last_update": self.last_update
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RouteState':
        """Deserialize from dictionary."""
        cargo_state = CargoState()
        cargo_state.current_scu = data.get("current_scu", 0)
        cargo_state.loaded_objectives = [
            Objective.from_dict(obj) for obj in data.get("loaded_objectives", [])
        ]

        return cls(
            completed_stop_ids=set(data.get("completed_stop_ids", [])),
            current_location=data.get("current_location"),
            cargo_state=cargo_state,
            last_update=data.get("last_update", datetime.now().isoformat())
        )


class IncrementalRoutePlanner:
    """
    Plans routes incrementally, accounting for already-completed stops.

    Handles mid-route mission additions and recalculations.
    """

    def __init__(self, route_service):
        """
        Initialize planner.

        Args:
            route_service: RouteService instance for route planning
        """
        self.route_service = route_service
        self.route_state = RouteState()

    def set_route_state(self, route_state: RouteState) -> None:
        """Set the current route state."""
        self.route_state = route_state

    def get_route_state(self) -> RouteState:
        """Get the current route state."""
        return self.route_state

    def plan_from_current_state(
        self,
        new_missions: List[Mission],
        ship_capacity: int
    ) -> tuple[List[Stop], bool, Optional[str]]:
        """
        Plan route from current state with new missions.

        This is the key method that handles:
        1. Already loaded cargo (must deliver)
        2. Current location (continue from here)
        3. New mission objectives (add to route)

        Args:
            new_missions: Newly accepted missions to add
            ship_capacity: Ship cargo capacity in SCU

        Returns:
            Tuple of (stops, is_valid, error_message)
        """
        logger.info(f"Planning route from {self.route_state.current_location or 'start'} "
                   f"with {self.route_state.cargo_state.current_scu} SCU loaded")

        # Collect all objectives from new missions
        new_objectives = []
        for mission in new_missions:
            new_objectives.extend(mission.objectives)

        # Already loaded cargo MUST be delivered first (prioritize)
        pending_deliveries = self.route_state.get_pending_deliveries()

        # Check if current cargo + new missions fit in ship
        current_scu = self.route_state.cargo_state.current_scu
        max_additional_scu = max((obj.scu_amount for obj in new_objectives), default=0)

        if current_scu + max_additional_scu > ship_capacity:
            error_msg = (f"Cannot add missions: current cargo ({current_scu} SCU) + "
                        f"new cargo ({max_additional_scu} SCU) exceeds ship capacity ({ship_capacity} SCU)")
            logger.warning(error_msg)
            return [], False, error_msg

        # Build stops
        stops = []
        stop_number = len(self.route_state.completed_stop_ids) + 1
        current_cargo = current_scu
        current_loc = self.route_state.current_location

        # Group objectives by location
        location_actions = self._group_objectives_by_location(pending_deliveries, new_objectives)

        # Plan delivery stops for already-loaded cargo first
        delivery_locations = [loc for loc, actions in location_actions.items()
                             if actions["deliveries"]]

        # Then pickup/delivery stops for new missions
        remaining_locations = [loc for loc in location_actions.keys()
                              if loc not in delivery_locations]

        # Create stops in order
        for location in delivery_locations + remaining_locations:
            actions = location_actions[location]

            cargo_before = current_cargo

            # Process deliveries first (unload)
            for delivery in actions["deliveries"]:
                current_cargo -= delivery.scu_amount

            # Then pickups (load)
            for pickup in actions["pickups"]:
                current_cargo += pickup.scu_amount

                # Check capacity
                if current_cargo > ship_capacity:
                    error_msg = f"Route would exceed ship capacity at {location}: {current_cargo} > {ship_capacity} SCU"
                    logger.warning(error_msg)
                    return [], False, error_msg

            # Create stop
            stop = Stop(
                location=location,
                stop_number=stop_number,
                pickups=actions["pickups"],
                deliveries=actions["deliveries"],
                cargo_before=cargo_before,
                cargo_after=current_cargo
            )
            stops.append(stop)
            stop_number += 1
            current_loc = location

        logger.info(f"Planned {len(stops)} stops from current state")
        return stops, True, None

    def _group_objectives_by_location(
        self,
        pending_deliveries: List[Objective],
        new_objectives: List[Objective]
    ) -> Dict[str, Dict[str, List[Objective]]]:
        """Group objectives by location."""
        from collections import defaultdict

        location_actions = defaultdict(lambda: {"pickups": [], "deliveries": []})

        # Add pending deliveries (already loaded cargo)
        for obj in pending_deliveries:
            location_actions[obj.deliver_to]["deliveries"].append(obj)

        # Add new objectives
        for obj in new_objectives:
            location_actions[obj.collect_from]["pickups"].append(obj)
            location_actions[obj.deliver_to]["deliveries"].append(obj)

        return dict(location_actions)

    def reset_route(self) -> None:
        """Reset route state to beginning."""
        self.route_state.reset()
        logger.info("Route reset to start")
