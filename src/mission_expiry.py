"""
Mission expiry tracking and prioritization.

Parses availability time and calculates urgency for route planning.
"""

import re
from datetime import datetime, timedelta
from typing import Optional, Tuple, List
from enum import IntEnum

from src.domain.models import Mission
from src.logger import get_logger

logger = get_logger()


class UrgencyLevel(IntEnum):
    """Mission urgency levels."""
    CRITICAL = 1   # < 30 minutes
    HIGH = 2       # 30min - 1hr
    MEDIUM = 3     # 1hr - 3hrs
    LOW = 4        # > 3hrs
    NO_LIMIT = 5   # N/A or unlimited


class MissionExpiry:
    """Tracks and calculates mission expiry."""

    @staticmethod
    def parse_availability(availability: str) -> Optional[timedelta]:
        """
        Parse availability string to timedelta.

        Supports formats:
        - "HH:MM:SS" (e.g., "01:45:30")
        - "N/A" (no time limit)

        Args:
            availability: Time string

        Returns:
            timedelta object or None if N/A
        """
        if not availability or availability.upper() == "N/A":
            return None

        # Try HH:MM:SS format
        try:
            parts = availability.split(":")
            if len(parts) == 3:
                hours, minutes, seconds = map(int, parts)
                return timedelta(hours=hours, minutes=minutes, seconds=seconds)
        except (ValueError, AttributeError):
            pass

        # Try natural language (e.g., "1h 45m 30s")
        try:
            total_seconds = 0

            hours_match = re.search(r'(\d+)\s*h(?:ours?)?', availability, re.IGNORECASE)
            if hours_match:
                total_seconds += int(hours_match.group(1)) * 3600

            mins_match = re.search(r'(\d+)\s*m(?:in(?:utes?)?)?', availability, re.IGNORECASE)
            if mins_match:
                total_seconds += int(mins_match.group(1)) * 60

            secs_match = re.search(r'(\d+)\s*s(?:ec(?:onds?)?)?', availability, re.IGNORECASE)
            if secs_match:
                total_seconds += int(secs_match.group(1))

            if total_seconds > 0:
                return timedelta(seconds=total_seconds)
        except (ValueError, AttributeError):
            pass

        logger.warning(f"Could not parse availability: {availability}")
        return None

    @staticmethod
    def get_urgency_level(availability: str) -> UrgencyLevel:
        """
        Get urgency level for a mission.

        Args:
            availability: Availability time string

        Returns:
            UrgencyLevel enum
        """
        time_remaining = MissionExpiry.parse_availability(availability)

        if time_remaining is None:
            return UrgencyLevel.NO_LIMIT

        total_minutes = time_remaining.total_seconds() / 60

        if total_minutes < 30:
            return UrgencyLevel.CRITICAL
        elif total_minutes < 60:
            return UrgencyLevel.HIGH
        elif total_minutes < 180:
            return UrgencyLevel.MEDIUM
        else:
            return UrgencyLevel.LOW

    @staticmethod
    def is_expiring_soon(availability: str, threshold_minutes: int = 30) -> bool:
        """
        Check if mission is expiring soon.

        Args:
            availability: Availability time string
            threshold_minutes: Threshold in minutes

        Returns:
            True if expiring within threshold
        """
        time_remaining = MissionExpiry.parse_availability(availability)

        if time_remaining is None:
            return False

        return time_remaining.total_seconds() / 60 < threshold_minutes

    @staticmethod
    def get_expiry_color(urgency: UrgencyLevel) -> str:
        """
        Get color code for urgency level.

        Args:
            urgency: UrgencyLevel enum

        Returns:
            Color string (for UI)
        """
        color_map = {
            UrgencyLevel.CRITICAL: "red",
            UrgencyLevel.HIGH: "orange",
            UrgencyLevel.MEDIUM: "yellow",
            UrgencyLevel.LOW: "green",
            UrgencyLevel.NO_LIMIT: "blue"
        }
        return color_map.get(urgency, "black")

    @staticmethod
    def format_time_remaining(availability: str) -> str:
        """
        Format time remaining in human-readable format.

        Args:
            availability: Availability time string

        Returns:
            Formatted string
        """
        time_remaining = MissionExpiry.parse_availability(availability)

        if time_remaining is None:
            return "No time limit"

        total_seconds = int(time_remaining.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60

        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        else:
            return f"{seconds}s"


class MissionPrioritizer:
    """Prioritizes missions based on multiple factors."""

    def __init__(self, location_hierarchy=None):
        """
        Initialize prioritizer.

        Args:
            location_hierarchy: LocationHierarchy instance for proximity
        """
        self.location_hierarchy = location_hierarchy

    def calculate_priority_score(
        self,
        mission: Mission,
        current_location: Optional[str] = None,
        weight_urgency: float = 0.4,
        weight_reward: float = 0.3,
        weight_proximity: float = 0.3
    ) -> float:
        """
        Calculate priority score for a mission.

        Lower score = higher priority.

        Args:
            mission: Mission to score
            current_location: Current player location
            weight_urgency: Weight for urgency factor (0-1)
            weight_reward: Weight for reward factor (0-1)
            weight_proximity: Weight for proximity factor (0-1)

        Returns:
            Priority score (lower is better)
        """
        # Urgency score (1-5, lower is more urgent)
        urgency = MissionExpiry.get_urgency_level(mission.availability)
        urgency_score = int(urgency)

        # Reward score (higher reward = lower score)
        # Normalize to 1-5 range
        reward_score = max(1, min(5, 6 - (mission.reward / 20000)))

        # Proximity score (1-10)
        proximity_score = 5  # Default middle value
        if current_location and self.location_hierarchy:
            # Get closest source location
            source_locs = mission.source_locations
            if source_locs:
                weights = [
                    self.location_hierarchy.calculate_proximity_weight(current_location, loc)
                    for loc in source_locs
                ]
                proximity_score = min(weights)

        # Weighted combination
        total_score = (
            urgency_score * weight_urgency +
            reward_score * weight_reward +
            proximity_score * weight_proximity
        )

        return total_score

    def sort_by_priority(
        self,
        missions: List[Mission],
        current_location: Optional[str] = None
    ) -> List[Tuple[Mission, float]]:
        """
        Sort missions by priority.

        Args:
            missions: List of missions to sort
            current_location: Optional current location

        Returns:
            List of (mission, score) tuples, sorted by priority
        """
        scored = [
            (mission, self.calculate_priority_score(mission, current_location))
            for mission in missions
        ]

        return sorted(scored, key=lambda x: x[1])

    def get_urgent_missions(
        self,
        missions: List[Mission],
        threshold: UrgencyLevel = UrgencyLevel.HIGH
    ) -> List[Mission]:
        """
        Get missions at or above urgency threshold.

        Args:
            missions: List of missions
            threshold: Minimum urgency level

        Returns:
            Filtered list of urgent missions
        """
        urgent = []

        for mission in missions:
            urgency = MissionExpiry.get_urgency_level(mission.availability)
            if urgency <= threshold:
                urgent.append(mission)

        return urgent

    def suggest_next_mission(
        self,
        missions: List[Mission],
        current_location: Optional[str] = None
    ) -> Optional[Mission]:
        """
        Suggest the next best mission to do.

        Args:
            missions: Available missions
            current_location: Current player location

        Returns:
            Suggested mission or None
        """
        if not missions:
            return None

        sorted_missions = self.sort_by_priority(missions, current_location)
        return sorted_missions[0][0]
