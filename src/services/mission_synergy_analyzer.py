"""
Mission Synergy Analyzer
Evaluates how well new missions fit with currently active missions.
"""

from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass

from src.domain.models import Mission, Objective, MissionStatus
from src.services.vrp_solver import VRPSolver
from src.logger import get_logger

logger = get_logger()


@dataclass
class SynergyMetrics:
    """Synergy analysis results for a candidate mission."""

    # Core metrics
    location_overlap_count: int  # Number of shared pickup/delivery locations
    total_locations_before: int  # Unique locations before adding mission
    total_locations_after: int  # Unique locations after adding mission

    current_scu: float  # Current total SCU from active missions
    new_scu: float  # SCU from new mission
    total_scu: float  # Total SCU after adding mission
    ship_capacity: float  # Ship's cargo capacity
    capacity_utilization_pct: float  # Percentage of ship capacity used

    route_efficiency_impact: float  # Impact on route efficiency (lower is better, 0 = no impact)
    profit_per_time_ratio: float  # New mission's aUEC per hour
    avg_profit_per_time_ratio: Optional[float]  # Average of active missions

    # Warnings
    exceeds_capacity: bool  # True if total SCU > ship capacity
    exceeds_threshold: bool  # True if utilization > threshold
    low_synergy: bool  # True if synergy score is low
    timing_warning: Optional[str]  # Warning about tight timing

    # Overall assessment
    synergy_score: float  # 0-100 score indicating how well mission fits
    recommendation: str  # "accept" or "skip"
    recommendation_reason: str  # Brief explanation

    # Display text
    inline_summary: str  # Compact text for UI display

    def __str__(self):
        return self.inline_summary


class MissionSynergyAnalyzer:
    """Analyzes synergy between new missions and active missions."""

    def __init__(
        self,
        ship_capacity: float = 128.0,
        capacity_threshold_pct: float = 80.0,
        low_synergy_threshold: float = 30.0,
        check_timing: bool = True
    ):
        """
        Initialize the synergy analyzer.

        Args:
            ship_capacity: Ship's cargo capacity in SCU
            capacity_threshold_pct: Warn when capacity exceeds this percentage
            low_synergy_threshold: Flag missions below this synergy score
            check_timing: Whether to check timing feasibility
        """
        self.ship_capacity = ship_capacity
        self.capacity_threshold_pct = capacity_threshold_pct
        self.low_synergy_threshold = low_synergy_threshold
        self.check_timing = check_timing

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
        # Calculate location overlap
        location_overlap = self._calculate_location_overlap(
            candidate_mission, active_missions
        )

        # Calculate capacity utilization
        capacity_metrics = self._calculate_capacity_metrics(
            candidate_mission, active_missions
        )

        # Calculate route efficiency impact
        route_impact = self._calculate_route_efficiency_impact(
            candidate_mission, active_missions
        )

        # Calculate profit per time ratio
        profit_metrics = self._calculate_profit_metrics(
            candidate_mission, active_missions
        )

        # Check timing feasibility
        timing_warning = None
        if self.check_timing:
            timing_warning = self._check_timing_feasibility(
                candidate_mission, active_missions
            )

        # Calculate overall synergy score
        synergy_score = self._calculate_synergy_score(
            location_overlap,
            capacity_metrics,
            route_impact,
            profit_metrics
        )

        # Generate warnings
        exceeds_capacity = capacity_metrics['total_scu'] > self.ship_capacity
        exceeds_threshold = capacity_metrics['utilization_pct'] > self.capacity_threshold_pct
        low_synergy = synergy_score < self.low_synergy_threshold

        # Generate recommendation
        recommendation, reason = self._generate_recommendation(
            synergy_score,
            exceeds_capacity,
            low_synergy,
            timing_warning
        )

        # Generate inline summary
        inline_summary = self._generate_inline_summary(
            location_overlap,
            capacity_metrics,
            route_impact,
            profit_metrics,
            synergy_score
        )

        return SynergyMetrics(
            location_overlap_count=location_overlap['overlap_count'],
            total_locations_before=location_overlap['locations_before'],
            total_locations_after=location_overlap['locations_after'],
            current_scu=capacity_metrics['current_scu'],
            new_scu=capacity_metrics['new_scu'],
            total_scu=capacity_metrics['total_scu'],
            ship_capacity=self.ship_capacity,
            capacity_utilization_pct=capacity_metrics['utilization_pct'],
            route_efficiency_impact=route_impact,
            profit_per_time_ratio=profit_metrics['candidate_ratio'],
            avg_profit_per_time_ratio=profit_metrics['avg_ratio'],
            exceeds_capacity=exceeds_capacity,
            exceeds_threshold=exceeds_threshold,
            low_synergy=low_synergy,
            timing_warning=timing_warning,
            synergy_score=synergy_score,
            recommendation=recommendation,
            recommendation_reason=reason,
            inline_summary=inline_summary
        )

    def _calculate_location_overlap(
        self,
        candidate: Mission,
        active_missions: List[Mission]
    ) -> Dict:
        """Calculate location overlap between candidate and active missions."""
        if not active_missions:
            return {
                'overlap_count': 0,
                'locations_before': 0,
                'locations_after': len(candidate.source_locations) + len(candidate.destination_locations)
            }

        # Get all unique locations from active missions
        active_locations = set()
        for mission in active_missions:
            active_locations.update(mission.source_locations)
            active_locations.update(mission.destination_locations)

        # Get candidate locations
        candidate_locations = set(candidate.source_locations + candidate.destination_locations)

        # Calculate overlap
        overlap = active_locations.intersection(candidate_locations)

        # Calculate total unique locations after adding candidate
        all_locations = active_locations.union(candidate_locations)

        return {
            'overlap_count': len(overlap),
            'locations_before': len(active_locations),
            'locations_after': len(all_locations)
        }

    def _calculate_capacity_metrics(
        self,
        candidate: Mission,
        active_missions: List[Mission]
    ) -> Dict:
        """Calculate capacity utilization metrics."""
        current_scu = sum(m.total_scu for m in active_missions)
        new_scu = candidate.total_scu
        total_scu = current_scu + new_scu
        utilization_pct = (total_scu / self.ship_capacity * 100) if self.ship_capacity > 0 else 0

        return {
            'current_scu': current_scu,
            'new_scu': new_scu,
            'total_scu': total_scu,
            'utilization_pct': utilization_pct
        }

    def _calculate_route_efficiency_impact(
        self,
        candidate: Mission,
        active_missions: List[Mission]
    ) -> float:
        """
        Calculate route efficiency impact using VRP solver.
        Returns a score where 0 = perfect fit, higher = worse fit.
        """
        if not active_missions:
            # No comparison possible, neutral impact
            return 0.0

        try:
            # Create VRP solver
            solver = VRPSolver(ship_capacity=int(self.ship_capacity))

            # Solve with active missions only
            route_before = solver.solve(active_missions, optimization_level='basic')

            # Solve with candidate mission added
            all_missions = active_missions + [candidate]
            route_after = solver.solve(all_missions, optimization_level='basic')

            # Calculate efficiency impact (simplified - could use actual distance)
            # For now, use number of stops as proxy
            stops_before = len(route_before.stops) if route_before else 0
            stops_after = len(route_after.stops) if route_after else 0

            # Lower impact is better
            # If we add minimal stops, impact is low
            impact = (stops_after - stops_before) / max(stops_before, 1)

            return max(0, impact * 100)  # Normalize to 0-100 scale

        except Exception as e:
            # If VRP fails, return neutral impact
            logger.debug(f"VRP solve failed during synergy analysis: {e}")
            return 50.0

    def _calculate_profit_metrics(
        self,
        candidate: Mission,
        active_missions: List[Mission]
    ) -> Dict:
        """Calculate profit per time ratio metrics."""
        # Parse candidate availability to hours
        candidate_hours = self._availability_to_hours(candidate.availability)
        candidate_ratio = candidate.reward / candidate_hours if candidate_hours > 0 else 0

        # Calculate average for active missions
        avg_ratio = None
        if active_missions:
            total_reward = 0
            total_hours = 0
            for mission in active_missions:
                hours = self._availability_to_hours(mission.availability)
                if hours > 0:
                    total_reward += mission.reward
                    total_hours += hours

            if total_hours > 0:
                avg_ratio = total_reward / total_hours

        return {
            'candidate_ratio': candidate_ratio,
            'avg_ratio': avg_ratio
        }

    def _availability_to_hours(self, availability: str) -> float:
        """Convert HH:MM:SS availability string to hours."""
        try:
            parts = availability.split(':')
            if len(parts) == 3:
                hours = int(parts[0])
                minutes = int(parts[1])
                seconds = int(parts[2])
                return hours + minutes / 60 + seconds / 3600
            return 0
        except (ValueError, AttributeError):
            return 0

    def _check_timing_feasibility(
        self,
        candidate: Mission,
        active_missions: List[Mission]
    ) -> Optional[str]:
        """
        Check if all missions can be completed before expiry.

        Time estimates per stop:
        - Landing: 1 min
        - Loading/unloading: 4 min per 20 SCU (0.2 min/SCU)
        - Takeoff: 1 min
        - Travel: 3 min average
        """
        if not active_missions:
            return None

        # Find mission with shortest time remaining
        all_missions = active_missions + [candidate]
        min_hours = float('inf')
        min_mission_id = None

        for mission in all_missions:
            hours = self._availability_to_hours(mission.availability)
            if hours < min_hours:
                min_hours = hours
                min_mission_id = mission.id

        # Estimate time based on realistic stop durations
        estimated_minutes = 0

        for mission in all_missions:
            for obj in mission.objectives:
                # Each objective = 2 stops (pickup + delivery)
                scu = obj.scu_amount

                # Per stop time breakdown:
                landing_takeoff = 2  # 1 min each
                cargo_ops = scu * 0.2  # 4 min per 20 SCU = 0.2 min/SCU
                travel = 3  # Average travel time

                minutes_per_stop = landing_takeoff + cargo_ops + travel

                # 2 stops per objective (pickup + delivery)
                estimated_minutes += minutes_per_stop * 2

        estimated_hours = estimated_minutes / 60

        if estimated_hours > min_hours * 0.7:  # Use 70% of time as buffer (more realistic)
            return f"Tight timing: ~{estimated_hours:.1f}h needed, {min_hours:.1f}h available"

        return None

    def _calculate_synergy_score(
        self,
        location_overlap: Dict,
        capacity_metrics: Dict,
        route_impact: float,
        profit_metrics: Dict
    ) -> float:
        """
        Calculate overall synergy score (0-100).
        Higher is better.
        """
        score = 0.0

        # Location overlap component (0-40 points)
        # More overlap = better score
        if location_overlap['locations_before'] > 0:
            overlap_ratio = location_overlap['overlap_count'] / location_overlap['locations_before']
            score += overlap_ratio * 40

        # Capacity utilization component (0-30 points)
        # Sweet spot is 60-85% utilization
        util = capacity_metrics['utilization_pct']
        if util <= 85:
            score += 30 * (util / 85)
        else:
            # Penalty for over-utilization
            score += max(0, 30 * (1 - (util - 85) / 15))

        # Route efficiency component (0-20 points)
        # Lower impact = better score
        route_score = max(0, 20 - (route_impact / 5))
        score += route_score

        # Profit ratio component (0-10 points)
        # Compare to average
        if profit_metrics['avg_ratio'] is not None and profit_metrics['avg_ratio'] > 0:
            ratio_comparison = profit_metrics['candidate_ratio'] / profit_metrics['avg_ratio']
            score += min(10, ratio_comparison * 10)
        else:
            score += 5  # Neutral if no comparison

        return min(100, max(0, score))

    def _generate_recommendation(
        self,
        synergy_score: float,
        exceeds_capacity: bool,
        low_synergy: bool,
        timing_warning: Optional[str]
    ) -> Tuple[str, str]:
        """Generate accept/skip recommendation with reason."""
        if exceeds_capacity:
            return "skip", "Exceeds ship capacity"

        if timing_warning and "Tight timing" in timing_warning:
            return "skip", "Insufficient time to complete"

        if synergy_score >= 70:
            return "accept", "High synergy - Recommended"
        elif synergy_score >= 40:
            return "accept", "Moderate synergy - Consider accepting"
        else:
            return "skip", "Low synergy - Consider skipping"

    def _generate_inline_summary(
        self,
        location_overlap: Dict,
        capacity_metrics: Dict,
        route_impact: float,
        profit_metrics: Dict,
        synergy_score: float
    ) -> str:
        """Generate compact inline summary text."""
        parts = []

        # Location overlap
        if location_overlap['overlap_count'] > 0:
            parts.append(f"{location_overlap['overlap_count']} shared stop{'s' if location_overlap['overlap_count'] > 1 else ''}")
        else:
            new_locations = location_overlap['locations_after'] - location_overlap['locations_before']
            parts.append(f"{new_locations} new location{'s' if new_locations > 1 else ''}")

        # Capacity
        parts.append(f"+{capacity_metrics['new_scu']:.0f} SCU ({capacity_metrics['utilization_pct']:.0f}% full)")

        # Route efficiency
        if route_impact < 20:
            parts.append("Efficient route")
        elif route_impact < 50:
            parts.append("Moderate route impact")
        else:
            parts.append("Inefficient route")

        # Value comparison
        if profit_metrics['avg_ratio'] is not None:
            ratio = profit_metrics['candidate_ratio'] / profit_metrics['avg_ratio']
            if ratio > 1.2:
                parts.append("Excellent value")
            elif ratio > 0.8:
                parts.append("Good value")
            else:
                parts.append("Below average value")

        return " • ".join(parts)
