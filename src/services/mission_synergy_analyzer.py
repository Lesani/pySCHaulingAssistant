"""
Mission Synergy Analyzer
Evaluates how well new missions fit with currently active missions.
Uses location proximity and route order to calculate synergy.
"""

from typing import List, Optional
from dataclasses import dataclass

from src.domain.models import Mission
from src.location_proximity import LocationProximity
from src.services.vrp_solver import VRPSolver
from src.logger import get_logger

logger = get_logger()


@dataclass
class SynergyMetrics:
    """Synergy analysis results for a candidate mission."""

    synergy_score: float          # 0-100
    shared_stops: int             # Exact location matches
    nearby_stops: int             # Proximity 1-2 matches (same moon/planet)
    new_stops: int                # No proximity match (far locations)
    total_candidate_stops: int    # Total stops in candidate mission

    current_scu: float            # SCU from active missions
    new_scu: float                # SCU from candidate mission
    total_scu: float              # Total after adding candidate
    ship_capacity: float          # Ship cargo capacity
    exceeds_capacity: bool        # True if over capacity

    verdict: str                  # Short recommendation text
    verdict_color: str            # "green", "yellow", "red"


class MissionSynergyAnalyzer:
    """Analyzes synergy between new missions and active missions."""

    # Proximity score mapping (proximity level -> score percentage)
    PROXIMITY_SCORES = {
        0: 100,  # Exact match
        1: 85,   # Same moon/station area (narrow)
        2: 60,   # Same planet + L1/L2 (wide)
        3: 20,   # Different planet/L3+/gateway (far)
    }

    def __init__(
        self,
        ship_capacity: float = 128.0,
        capacity_threshold_pct: float = 80.0,
        **kwargs  # Accept but ignore legacy params
    ):
        """
        Initialize the synergy analyzer.

        Args:
            ship_capacity: Ship's cargo capacity in SCU
            capacity_threshold_pct: Warn when capacity exceeds this percentage
        """
        self.ship_capacity = ship_capacity
        self.capacity_threshold_pct = capacity_threshold_pct
        self.proximity = LocationProximity()

    def analyze(
        self,
        candidate_mission: Mission,
        active_missions: List[Mission]
    ) -> SynergyMetrics:
        """
        Analyze how well a candidate mission fits with active missions.

        Args:
            candidate_mission: The mission to evaluate
            active_missions: List of currently active missions

        Returns:
            SynergyMetrics with analysis results
        """
        # Get unique candidate locations (pickups and deliveries)
        candidate_stops = set(self._get_mission_stops(candidate_mission))
        total_candidate_stops = len(candidate_stops)

        # Calculate capacity
        current_scu = sum(m.total_scu for m in active_missions)
        new_scu = candidate_mission.total_scu
        total_scu = current_scu + new_scu
        exceeds_capacity = total_scu > self.ship_capacity

        # No active missions = neutral synergy (100%)
        if not active_missions:
            return SynergyMetrics(
                synergy_score=100.0,
                shared_stops=0,
                nearby_stops=0,
                new_stops=total_candidate_stops,
                total_candidate_stops=total_candidate_stops,
                current_scu=current_scu,
                new_scu=new_scu,
                total_scu=total_scu,
                ship_capacity=self.ship_capacity,
                exceeds_capacity=exceeds_capacity,
                verdict="First mission - no comparison needed",
                verdict_color="green"
            )

        # Get all stops from active missions
        active_stops = set()
        for mission in active_missions:
            active_stops.update(self._get_mission_stops(mission))

        # Calculate location proximity scores
        shared_stops = 0
        nearby_stops = 0
        new_stops = 0
        location_scores = []

        for stop in candidate_stops:
            best_proximity = 3  # Start with "far"

            for active_stop in active_stops:
                proximity = self.proximity.calculate_proximity(stop, active_stop)
                best_proximity = min(best_proximity, proximity)
                if best_proximity == 0:
                    break  # Can't get better than exact match

            # Track stop categories
            if best_proximity == 0:
                shared_stops += 1
            elif best_proximity <= 2:
                nearby_stops += 1
            else:
                new_stops += 1

            location_scores.append(self.PROXIMITY_SCORES.get(best_proximity, 20))

        # Calculate average location score
        location_match_avg = sum(location_scores) / len(location_scores) if location_scores else 50

        # Calculate route order impact using VRP
        route_order_adjustment = self._calculate_route_order_impact(
            candidate_mission, active_missions
        )

        # Final synergy score
        synergy_score = max(0, min(100, location_match_avg + route_order_adjustment))

        # Generate verdict
        verdict, verdict_color = self._generate_verdict(
            synergy_score, exceeds_capacity, shared_stops, nearby_stops
        )

        return SynergyMetrics(
            synergy_score=synergy_score,
            shared_stops=shared_stops,
            nearby_stops=nearby_stops,
            new_stops=new_stops,
            total_candidate_stops=total_candidate_stops,
            current_scu=current_scu,
            new_scu=new_scu,
            total_scu=total_scu,
            ship_capacity=self.ship_capacity,
            exceeds_capacity=exceeds_capacity,
            verdict=verdict,
            verdict_color=verdict_color
        )

    def _get_mission_stops(self, mission: Mission) -> List[str]:
        """Get all pickup and delivery locations from a mission."""
        stops = []
        for obj in mission.objectives:
            if obj.collect_from:
                stops.append(obj.collect_from)
            if obj.deliver_to:
                stops.append(obj.deliver_to)
        return stops

    def _calculate_route_order_impact(
        self,
        candidate: Mission,
        active_missions: List[Mission]
    ) -> float:
        """
        Calculate route order impact using VRP solver.

        Returns adjustment value:
        - Positive if candidate fits well in route order
        - Negative if it would require backtracking
        """
        if not active_missions:
            return 0.0

        try:
            # Solve VRP for active missions to get current route
            solver = VRPSolver(ship_capacity=int(self.ship_capacity))
            current_route = solver.solve(active_missions, optimization_level='basic')

            if not current_route or not current_route.stops:
                return 0.0

            # Build location order from current route
            route_order = [stop.location for stop in current_route.stops]

            # Check each objective's pickup→delivery order against route
            adjustment = 0.0
            objectives_checked = 0

            for obj in candidate.objectives:
                pickup = obj.collect_from
                delivery = obj.deliver_to

                if not pickup or not delivery:
                    continue

                # Find positions in route (or nearest matches)
                pickup_pos = self._find_position_in_route(pickup, route_order)
                delivery_pos = self._find_position_in_route(delivery, route_order)

                if pickup_pos is not None and delivery_pos is not None:
                    if pickup_pos < delivery_pos:
                        # Good: pickup before delivery in route
                        adjustment += 10
                    else:
                        # Bad: would require backtracking
                        adjustment -= 20
                    objectives_checked += 1

            # Average the adjustment if we checked any objectives
            if objectives_checked > 0:
                adjustment /= objectives_checked

            return adjustment

        except Exception as e:
            logger.debug(f"VRP route order check failed: {e}")
            return 0.0

    def _find_position_in_route(self, location: str, route_order: List[str]) -> Optional[int]:
        """
        Find position of location in route, considering proximity.
        Returns index or None if not found (even with proximity).
        """
        # First try exact match
        if location in route_order:
            return route_order.index(location)

        # Try proximity match (find closest location in route)
        best_pos = None
        best_proximity = 3

        for i, route_loc in enumerate(route_order):
            proximity = self.proximity.calculate_proximity(location, route_loc)
            if proximity < best_proximity:
                best_proximity = proximity
                best_pos = i

        # Only return position if reasonably close (proximity <= 2)
        if best_proximity <= 2:
            return best_pos

        return None

    def _generate_verdict(
        self,
        synergy_score: float,
        exceeds_capacity: bool,
        shared_stops: int,
        nearby_stops: int
    ) -> tuple:
        """Generate verdict text and color based on analysis.

        Color scheme:
        - 0-50%: red
        - 50-75%: orange
        - 75-85%: yellow
        - 85%+: green
        """

        if exceeds_capacity:
            return "Exceeds ship capacity!", "red"

        if synergy_score >= 85:
            if shared_stops > 0:
                return f"Excellent fit - {shared_stops} shared stop(s)", "green"
            elif nearby_stops > 0:
                return f"Excellent fit - {nearby_stops} nearby stop(s)", "green"
            else:
                return "Excellent fit with current route", "green"

        elif synergy_score >= 75:
            if shared_stops > 0:
                return f"Good fit - {shared_stops} shared stop(s)", "yellow"
            elif nearby_stops > 0:
                return f"Good fit - {nearby_stops} nearby stop(s)", "yellow"
            else:
                return "Good fit with current route", "yellow"

        elif synergy_score >= 50:
            if nearby_stops > 0:
                return f"Moderate fit - {nearby_stops} nearby stop(s)", "orange"
            else:
                return "Moderate fit - some route deviation", "orange"

        else:
            return "Poor fit - significant route deviation", "red"
