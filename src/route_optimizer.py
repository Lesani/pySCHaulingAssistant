"""
Route optimizer for hauling missions.

Provides grouping and route suggestion features with VRP solver integration.
"""

from collections import defaultdict
from typing import List, Dict, Any, Tuple, Optional

from src.services.vrp_solver import VRPSolver
from src.domain.models import Mission, Route


class RouteOptimizer:
    """
    Optimizes hauling mission routes and provides grouping.

    Integrates with VRP solver for advanced route optimization.
    """

    @staticmethod
    def create_vrp_route(
        missions: List[Dict[str, Any]],
        ship_capacity: int = 96,
        starting_location: Optional[str] = None,
        optimization_level: str = 'medium'
    ) -> Route:
        """
        Create optimized route using VRP solver.

        Args:
            missions: List of mission dictionaries
            ship_capacity: Ship cargo capacity in SCU (default: 96 for ARGO RAFT)
            starting_location: Optional starting location
            optimization_level: 'basic', 'medium', or 'advanced'

        Returns:
            Optimized Route object with proper cargo tracking

        Raises:
            ValueError: If route is infeasible due to capacity constraints
        """
        # Convert mission dicts to Mission objects
        mission_objects = [Mission.from_dict(m) for m in missions]

        # Create VRP solver
        solver = VRPSolver(ship_capacity=ship_capacity, starting_location=starting_location)

        # Solve and return
        return solver.solve(mission_objects, optimization_level=optimization_level)

    @staticmethod
    def validate_missions_capacity(
        missions: List[Dict[str, Any]],
        ship_capacity: int
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate if missions can fit within ship capacity.

        Args:
            missions: List of mission dictionaries
            ship_capacity: Ship cargo capacity in SCU

        Returns:
            Tuple of (is_feasible, error_message)
        """
        # Convert to Mission objects
        mission_objects = [Mission.from_dict(m) for m in missions]

        # Create solver and validate
        solver = VRPSolver(ship_capacity=ship_capacity)
        return solver.validate_missions_feasible(mission_objects)

    @staticmethod
    def group_by_source(missions: List[Dict[str, Any]], location_matcher=None) -> Dict[str, List[Dict[str, Any]]]:
        """
        Group missions by their source location(s).

        Args:
            missions: List of mission dictionaries
            location_matcher: Optional LocationMatcher for normalizing location names

        Returns:
            Dict mapping source location to list of missions
        """
        grouped = defaultdict(list)

        for mission in missions:
            sources = set()
            for obj in mission.get("objectives", []):
                source = obj.get("collect_from", "Unknown")
                # Normalize location name if matcher provided
                if location_matcher:
                    source = location_matcher.normalize_location(source)
                sources.add(source)

            # Add mission to all source groups
            for source in sources:
                grouped[source].append(mission)

        return dict(grouped)

    @staticmethod
    def group_by_destination(missions: List[Dict[str, Any]], location_matcher=None) -> Dict[str, List[Dict[str, Any]]]:
        """
        Group missions by their destination location(s).

        Args:
            missions: List of mission dictionaries
            location_matcher: Optional LocationMatcher for normalizing location names

        Returns:
            Dict mapping destination location to list of missions
        """
        grouped = defaultdict(list)

        for mission in missions:
            destinations = set()
            for obj in mission.get("objectives", []):
                dest = obj.get("deliver_to", "Unknown")
                # Normalize location name if matcher provided
                if location_matcher:
                    dest = location_matcher.normalize_location(dest)
                destinations.add(dest)

            # Add mission to all destination groups
            for dest in destinations:
                grouped[dest].append(mission)

        return dict(grouped)

    @staticmethod
    def calculate_group_totals(missions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Calculate totals for a group of missions.

        Args:
            missions: List of mission dictionaries

        Returns:
            Dict with total_reward, total_scu, mission_count
        """
        total_reward = sum(m.get("reward", 0) for m in missions)
        total_scu = sum(
            sum(obj.get("scu_amount", 0) for obj in m.get("objectives", []))
            for m in missions
        )

        return {
            "total_reward": total_reward,
            "total_scu": total_scu,
            "mission_count": len(missions)
        }

    @staticmethod
    def suggest_route(missions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Suggest an optimal route order for missions.

        Currently implements a simple strategy:
        1. Group by source location
        2. Sort groups by total reward (descending)
        3. Return missions in that order

        Future: Can be enhanced with distance calculations

        Args:
            missions: List of mission dictionaries

        Returns:
            Missions reordered for optimal routing
        """
        if not missions:
            return []

        # Group by source
        grouped = RouteOptimizer.group_by_source(missions)

        # Calculate totals for each group
        group_scores = []
        for source, group_missions in grouped.items():
            totals = RouteOptimizer.calculate_group_totals(group_missions)
            score = totals["total_reward"]  # Can be enhanced with other factors
            group_scores.append((score, source, group_missions))

        # Sort by score (descending)
        group_scores.sort(reverse=True, key=lambda x: x[0])

        # Flatten back to mission list
        optimized = []
        seen_ids = set()

        for _, _, group_missions in group_scores:
            for mission in group_missions:
                # Avoid duplicates (mission might be in multiple groups)
                if mission.get("id") not in seen_ids:
                    optimized.append(mission)
                    seen_ids.add(mission.get("id"))

        return optimized

    @staticmethod
    def get_route_summary(missions: List[Dict[str, Any]]) -> str:
        """
        Generate a human-readable route summary.

        Args:
            missions: List of missions in suggested order

        Returns:
            Formatted string describing the route
        """
        if not missions:
            return "No missions to route."

        lines = ["Suggested Route Order:", ""]

        for i, mission in enumerate(missions, 1):
            reward = mission.get("reward", 0)
            objectives = mission.get("objectives", [])

            sources = list(set(obj.get("collect_from", "?") for obj in objectives))
            destinations = list(set(obj.get("deliver_to", "?") for obj in objectives))
            total_scu = sum(obj.get("scu_amount", 0) for obj in objectives)

            source_str = ", ".join(sources)
            dest_str = ", ".join(destinations)

            lines.append(f"{i}. {reward:,} aUEC - {total_scu} SCU")
            lines.append(f"   From: {source_str}")
            lines.append(f"   To: {dest_str}")
            lines.append("")

        return "\n".join(lines)
