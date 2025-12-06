"""
Worker functions for parallel route finding.

These functions must be module-level (not methods) to be picklable
for multiprocessing. They receive serializable data and return
serializable results.
"""

from typing import Dict, Any, List, Optional, Set, Tuple
from itertools import combinations

from src.domain.models import Mission, Objective, Route
from src.services.vrp_solver import VRPSolver
from src.logger import get_logger

logger = get_logger()


def scan_to_mission(scan: Dict[str, Any]) -> Optional[Mission]:
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

    except Exception:
        return None


def route_to_dict(route: Route) -> Dict[str, Any]:
    """Convert a Route object to a serializable dict."""
    return {
        "total_reward": route.total_reward,
        "total_scu": route.total_scu,
        "total_stops": route.total_stops,
        "stops": [
            {
                "location": stop.location,
                "pickup_scu": stop.total_pickup_scu,
                "delivery_scu": stop.total_delivery_scu,
                "cargo_after": stop.cargo_after
            }
            for stop in route.stops
        ]
    }


def estimate_stop_count(mission_scans: List[Dict[str, Any]]) -> int:
    """Estimate minimum stops for a set of missions."""
    locations = set()
    for scan in mission_scans:
        for obj in scan.get("mission_data", {}).get("objectives", []):
            locations.add(obj.get("collect_from", ""))
            locations.add(obj.get("deliver_to", ""))
    locations.discard("")
    return len(locations)


def get_scan_locations(scan: Dict[str, Any]) -> Set[str]:
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


def get_scan_reward(scan: Dict[str, Any]) -> float:
    """Get total reward from a scan."""
    return scan.get("mission_data", {}).get("reward", 0)


def get_scan_scu(scan: Dict[str, Any]) -> int:
    """Get total SCU from a scan."""
    objs = scan.get("mission_data", {}).get("objectives", [])
    return sum(o.get("scu_amount", 0) for o in objs)


def try_build_route_from_scans(
    mission_scans: List[Dict[str, Any]],
    max_stops: int,
    starting_location: Optional[str],
    ship_capacity: int
) -> Optional[Dict[str, Any]]:
    """
    Try to build a route from mission scans.

    Returns a dict with route data if successful, None otherwise.
    """
    try:
        # Quick check: estimate stops
        estimated_stops = estimate_stop_count(mission_scans)
        if estimated_stops > max_stops:
            return None

        # Convert scans to missions
        missions = []
        for scan in mission_scans:
            mission = scan_to_mission(scan)
            if mission:
                missions.append(mission)

        if not missions:
            return None

        # Create VRP solver
        solver = VRPSolver(
            ship_capacity=ship_capacity,
            starting_location=starting_location
        )

        # Check feasibility
        is_feasible, error = solver.validate_missions_feasible(missions)
        if not is_feasible:
            return None

        # Solve
        route = solver.solve(missions, 'medium', max_stops=max_stops)
        if route is None or route.total_stops > max_stops:
            return None

        # Return serializable result
        return {
            "route_data": route_to_dict(route),
            "total_reward": route.total_reward,
            "total_scu": route.total_scu,
            "stop_count": route.total_stops,
            "mission_count": len(missions)
        }

    except Exception:
        return None


# Constants for affinity calculation
AFFINITY_OVERLAP_BONUS = 0.15
AFFINITY_NEW_PENALTY = 0.05


def calculate_affinity_score(
    scan: Dict[str, Any],
    selected_locations: Set[str],
    fewest_stops_weight: int
) -> float:
    """Calculate affinity bonus for a scan based on location overlap."""
    if not selected_locations:
        return 0.0

    scan_locations = get_scan_locations(scan)
    base_reward = get_scan_reward(scan)

    overlap_count = len(scan_locations & selected_locations)
    new_count = len(scan_locations - selected_locations)

    stop_weight = max(0.1, fewest_stops_weight / 100.0)

    affinity = (
        overlap_count * base_reward * AFFINITY_OVERLAP_BONUS * stop_weight -
        new_count * base_reward * AFFINITY_NEW_PENALTY * stop_weight
    )

    return affinity


def greedy_from_start_worker(args: Tuple) -> Optional[Dict[str, Any]]:
    """
    Worker function for parallel greedy search from a starting point.

    Args:
        args: Tuple of (scored_scans, start_idx, filters_dict, weights_dict, ship_capacity)
              - scored_scans: List of (scan_dict, base_score) tuples
              - start_idx: Index of starting scan
              - filters_dict: {max_stops, starting_location}
              - weights_dict: {fewest_stops, ...}
              - ship_capacity: int

    Returns:
        Dict with route data and metrics, or None if no route found.
    """
    try:
        scored_scans, start_idx, filters_dict, weights_dict, ship_capacity = args

        max_stops = filters_dict["max_stops"]
        starting_location = filters_dict.get("starting_location")
        fewest_stops_weight = weights_dict.get("fewest_stops", 0)

        best_result = None
        selected_scans = []
        selected_locations: Set[str] = set()

        # Start with the specified scan
        start_scan, _ = scored_scans[start_idx]
        selected_scans.append(start_scan)
        selected_locations = get_scan_locations(start_scan)

        # Available scans (excluding start)
        available = [(s, score) for i, (s, score) in enumerate(scored_scans) if i != start_idx]

        while available:
            # Stop if we've hit the location limit
            if len(selected_locations) >= max_stops:
                break

            # Stop if best result already at max stops
            if best_result and best_result.get("stop_count", 0) >= max_stops:
                break

            best_scan = None
            best_combined_score = float('-inf')

            for scan, base_score in available:
                scan_locs = get_scan_locations(scan)
                potential_locs = selected_locations | scan_locs

                # Skip if would exceed max_stops
                if len(potential_locs) > max_stops:
                    continue

                # Calculate combined score with affinity
                affinity = calculate_affinity_score(scan, selected_locations, fewest_stops_weight)
                combined = base_score + affinity

                if combined > best_combined_score:
                    best_combined_score = combined
                    best_scan = scan

            if best_scan is None:
                break

            selected_scans.append(best_scan)
            selected_locations |= get_scan_locations(best_scan)
            available = [(s, score) for s, score in available if s is not best_scan]

            # Try to build route
            result = try_build_route_from_scans(
                selected_scans, max_stops, starting_location, ship_capacity
            )

            if result:
                if best_result is None or result["total_reward"] > best_result.get("total_reward", 0):
                    # Include the scan indices for deduplication
                    result["scan_indices"] = [
                        i for i, (s, _) in enumerate(scored_scans)
                        if any(s is sel for sel in selected_scans)
                    ]
                    best_result = result
            elif best_result:
                # Route became infeasible, stop adding
                break

        return best_result

    except Exception as e:
        logger.debug(f"Greedy worker failed: {e}")
        return None


def combinatorial_worker(args: Tuple) -> Optional[Dict[str, Any]]:
    """
    Worker function for evaluating a combination of scans.

    Args:
        args: Tuple of (scans, combo_indices, filters_dict, ship_capacity)
              - scans: List of all scan dicts
              - combo_indices: Tuple of indices to combine
              - filters_dict: {max_stops, starting_location}
              - ship_capacity: int

    Returns:
        Dict with route data and metrics, or None if no route found.
    """
    try:
        scans, combo_indices, filters_dict, ship_capacity = args

        max_stops = filters_dict["max_stops"]
        starting_location = filters_dict.get("starting_location")

        mission_scans = [scans[i] for i in combo_indices]

        result = try_build_route_from_scans(
            mission_scans, max_stops, starting_location, ship_capacity
        )

        if result:
            result["combo_indices"] = combo_indices

        return result

    except Exception as e:
        logger.debug(f"Combinatorial worker failed: {e}")
        return None


def batch_combinatorial_worker(args: Tuple) -> List[Dict[str, Any]]:
    """
    Worker function for evaluating a batch of combinations.

    Args:
        args: Tuple of (scans, combo_batch, filters_dict, ship_capacity)
              - scans: List of all scan dicts
              - combo_batch: List of combo_indices tuples to evaluate
              - filters_dict: {max_stops, starting_location}
              - ship_capacity: int

    Returns:
        List of successful route results.
    """
    try:
        scans, combo_batch, filters_dict, ship_capacity = args

        results = []
        for combo_indices in combo_batch:
            result = combinatorial_worker((scans, combo_indices, filters_dict, ship_capacity))
            if result:
                results.append(result)

        return results

    except Exception as e:
        logger.debug(f"Batch combinatorial worker failed: {e}")
        return []
