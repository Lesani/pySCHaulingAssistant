"""
Mission service for business logic operations.

Handles mission CRUD operations using domain models.
"""

from typing import List, Optional, Dict, Any

from src.domain.models import Mission, MissionStatus, Objective
from src.mission_manager import MissionManager
from src.logger import get_logger

logger = get_logger()


class MissionService:
    """
    Service for mission operations.

    Bridges between domain models and persistence layer.
    """

    def __init__(self, mission_manager: MissionManager):
        """
        Initialize service with mission manager.

        Args:
            mission_manager: Persistence layer for missions
        """
        self.mission_manager = mission_manager

    def create_mission(
        self,
        reward: float,
        availability: str,
        objectives_data: List[Dict[str, Any]]
    ) -> Mission:
        """
        Create a new mission.

        Args:
            reward: Mission reward in aUEC
            availability: Time remaining (HH:MM:SS or "N/A")
            objectives_data: List of objective dictionaries

        Returns:
            Created Mission object

        Raises:
            ValueError: If mission data is invalid
        """
        # Create objectives
        objectives = [Objective.from_dict(obj) for obj in objectives_data]

        # Create mission domain model
        mission = Mission(
            reward=reward,
            availability=availability,
            objectives=objectives
        )

        # Persist to storage
        mission_dict = mission.to_dict()
        self.mission_manager.add_mission({
            "reward": mission_dict["reward"],
            "availability": mission_dict["availability"],
            "objectives": mission_dict["objectives"]
        })

        logger.info(f"Created mission {mission.id} with {len(objectives)} objectives")
        return mission

    def get_mission(self, mission_id: str) -> Optional[Mission]:
        """
        Get a mission by ID.

        Args:
            mission_id: Mission UUID

        Returns:
            Mission object or None if not found
        """
        data = self.mission_manager.get_mission(mission_id)
        if not data:
            return None

        return Mission.from_dict(data)

    def get_all_missions(self, status: Optional[MissionStatus] = None) -> List[Mission]:
        """
        Get all missions, optionally filtered by status.

        Args:
            status: Optional status filter

        Returns:
            List of Mission objects
        """
        status_str = status.value if status else None
        missions_data = self.mission_manager.get_missions(status=status_str)

        missions = []
        for data in missions_data:
            try:
                mission = Mission.from_dict(data)
                missions.append(mission)
            except Exception as e:
                logger.warning(f"Failed to parse mission {data.get('id')}: {e}")
                continue

        return missions

    def get_active_missions(self) -> List[Mission]:
        """Get all active missions."""
        return self.get_all_missions(status=MissionStatus.ACTIVE)

    def update_mission(self, mission: Mission) -> bool:
        """
        Update an existing mission.

        Args:
            mission: Mission object with updated data

        Returns:
            True if updated successfully
        """
        mission_dict = mission.to_dict()
        success = self.mission_manager.update_mission(mission.id, {
            "reward": mission_dict["reward"],
            "availability": mission_dict["availability"],
            "objectives": mission_dict["objectives"]
        })

        if success:
            logger.info(f"Updated mission {mission.id}")
        else:
            logger.warning(f"Failed to update mission {mission.id}")

        return success

    def delete_mission(self, mission_id: str) -> bool:
        """
        Delete a mission.

        Args:
            mission_id: Mission UUID

        Returns:
            True if deleted successfully
        """
        success = self.mission_manager.delete_mission(mission_id)

        if success:
            logger.info(f"Deleted mission {mission_id}")
        else:
            logger.warning(f"Failed to delete mission {mission_id}")

        return success

    def mark_completed(self, mission_id: str) -> bool:
        """Mark a mission as completed."""
        return self.mission_manager.update_status(mission_id, MissionStatus.COMPLETED.value)

    def mark_expired(self, mission_id: str) -> bool:
        """Mark a mission as expired."""
        return self.mission_manager.update_status(mission_id, MissionStatus.EXPIRED.value)

    def mark_active(self, mission_id: str) -> bool:
        """Mark a mission as active."""
        return self.mission_manager.update_status(mission_id, MissionStatus.ACTIVE.value)

    def clear_all(self, status: Optional[MissionStatus] = None) -> int:
        """
        Clear all missions or missions with specific status.

        Args:
            status: Optional status filter

        Returns:
            Number of missions cleared
        """
        status_str = status.value if status else None
        count = self.mission_manager.clear_all(status_filter=status_str)
        logger.info(f"Cleared {count} mission(s)")
        return count

    def get_summary(self) -> Dict[str, Any]:
        """
        Get summary statistics.

        Returns:
            Dictionary with total_missions, active_missions, total_reward, total_scu
        """
        return self.mission_manager.get_summary()

    def calculate_total_reward(self, missions: List[Mission]) -> float:
        """Calculate total reward for a list of missions."""
        return sum(m.reward for m in missions)

    def calculate_total_scu(self, missions: List[Mission]) -> int:
        """Calculate total SCU for a list of missions."""
        return sum(m.total_scu for m in missions)

    def group_by_source(self, missions: List[Mission]) -> Dict[str, List[Mission]]:
        """
        Group missions by source locations.

        Args:
            missions: List of missions

        Returns:
            Dictionary mapping source location to list of missions
        """
        grouped = {}
        for mission in missions:
            for source in mission.source_locations:
                if source not in grouped:
                    grouped[source] = []
                grouped[source].append(mission)

        return grouped

    def group_by_destination(self, missions: List[Mission]) -> Dict[str, List[Mission]]:
        """
        Group missions by destination locations.

        Args:
            missions: List of missions

        Returns:
            Dictionary mapping destination location to list of missions
        """
        grouped = {}
        for mission in missions:
            for dest in mission.destination_locations:
                if dest not in grouped:
                    grouped[dest] = []
                grouped[dest].append(mission)

        return grouped
