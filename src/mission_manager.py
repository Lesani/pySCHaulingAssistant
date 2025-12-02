"""
Mission manager for CRUD operations on hauling missions.

Handles persistence to missions.json file with validation and backups.
"""

import json
import os
import shutil
from datetime import datetime
from typing import Dict, List, Any, Optional
from uuid import uuid4
from filelock import FileLock

from src.logger import get_logger
from src.validation import (
    validate_missions_file,
    validate_mission,
    sanitize_mission,
    create_versioned_file_structure,
    is_legacy_format,
    migrate_from_legacy
)

logger = get_logger()


class MissionManager:
    """Manages hauling mission storage and retrieval."""

    def __init__(self, storage_file: str = "missions.json", max_backups: int = 5) -> None:
        self.storage_file = storage_file
        self.lock_file = storage_file + ".lock"
        self.max_backups = max_backups
        self.missions: List[Dict[str, Any]] = []
        self.load()

    def add_mission(self, mission_data: Dict[str, Any]) -> str:
        """
        Add a new mission to the stack.

        Args:
            mission_data: Dict with reward, availability, objectives

        Returns:
            Mission ID (UUID)
        """
        mission_id = str(uuid4())

        # Populate mission_id in all objectives
        objectives = mission_data.get("objectives", [])
        for objective in objectives:
            if isinstance(objective, dict):
                objective["mission_id"] = mission_id

        mission = {
            "id": mission_id,
            "timestamp": datetime.now().isoformat(),
            "status": "active",
            **mission_data
        }
        self.missions.append(mission)
        self.save()
        return mission_id

    def get_missions(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get all missions, optionally filtered by status.

        Args:
            status: Filter by status (active, completed, expired) or None for all

        Returns:
            List of mission dictionaries
        """
        if status is None:
            return self.missions.copy()
        return [m for m in self.missions if m.get("status") == status]

    def get_mission(self, mission_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific mission by ID.

        Args:
            mission_id: UUID of the mission

        Returns:
            Mission dict or None if not found
        """
        for mission in self.missions:
            if mission["id"] == mission_id:
                return mission.copy()
        return None

    def update_mission(self, mission_id: str, mission_data: Dict[str, Any]) -> bool:
        """
        Update an existing mission.

        Args:
            mission_id: UUID of the mission
            mission_data: New mission data (reward, availability, objectives)

        Returns:
            True if updated, False if not found
        """
        for i, mission in enumerate(self.missions):
            if mission["id"] == mission_id:
                # Preserve id, timestamp, and status
                self.missions[i] = {
                    "id": mission["id"],
                    "timestamp": mission["timestamp"],
                    "status": mission.get("status", "active"),
                    **mission_data
                }
                self.save()
                return True
        return False

    def delete_mission(self, mission_id: str) -> bool:
        """
        Delete a mission from the stack.

        Args:
            mission_id: UUID of the mission

        Returns:
            True if deleted, False if not found
        """
        for i, mission in enumerate(self.missions):
            if mission["id"] == mission_id:
                del self.missions[i]
                self.save()
                return True
        return False

    def update_status(self, mission_id: str, status: str) -> bool:
        """
        Update mission status (active, completed, expired).

        Args:
            mission_id: UUID of the mission
            status: New status value

        Returns:
            True if updated, False if not found
        """
        for mission in self.missions:
            if mission["id"] == mission_id:
                mission["status"] = status
                self.save()
                return True
        return False

    def clear_all(self, status_filter: Optional[str] = None) -> int:
        """
        Clear all missions or missions with specific status.

        Args:
            status_filter: If specified, only clear missions with this status

        Returns:
            Number of missions cleared
        """
        if status_filter is None:
            count = len(self.missions)
            self.missions = []
        else:
            original_count = len(self.missions)
            self.missions = [m for m in self.missions if m.get("status") != status_filter]
            count = original_count - len(self.missions)

        if count > 0:
            self.save()
        return count

    def _create_backup(self) -> None:
        """Create a backup of the current missions file."""
        if not os.path.exists(self.storage_file):
            return

        try:
            # Create backup directory
            backup_dir = "backups"
            os.makedirs(backup_dir, exist_ok=True)

            # Timestamp for backup
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = os.path.join(backup_dir, f"missions_backup_{timestamp}.json")

            # Copy file
            shutil.copy2(self.storage_file, backup_path)
            logger.info(f"Created backup: {backup_path}")

            # Clean up old backups (keep only max_backups)
            self._cleanup_old_backups(backup_dir)

        except Exception as e:
            logger.error(f"Failed to create backup: {e}")

    def _cleanup_old_backups(self, backup_dir: str) -> None:
        """Remove old backups, keeping only the most recent max_backups."""
        try:
            # Get all backup files
            backups = [
                os.path.join(backup_dir, f)
                for f in os.listdir(backup_dir)
                if f.startswith("missions_backup_") and f.endswith(".json")
            ]

            # Sort by modification time (newest first)
            backups.sort(key=os.path.getmtime, reverse=True)

            # Remove old backups
            for old_backup in backups[self.max_backups:]:
                os.remove(old_backup)
                logger.debug(f"Removed old backup: {old_backup}")

        except Exception as e:
            logger.error(f"Failed to cleanup old backups: {e}")

    def save(self) -> None:
        """Save missions to disk with validation and file locking."""
        lock = FileLock(self.lock_file, timeout=10)

        try:
            with lock:
                # Create backup before saving
                self._create_backup()

                # Create versioned structure
                file_data = create_versioned_file_structure(self.missions)

                # Validate before saving
                is_valid, error_msg = validate_missions_file(file_data)
                if not is_valid:
                    logger.error(f"Validation failed before save: {error_msg}")
                    raise ValueError(f"Cannot save invalid data: {error_msg}")

                # Write to file
                with open(self.storage_file, "w", encoding="utf-8") as f:
                    json.dump(file_data, f, indent=2)

                logger.debug(f"Saved {len(self.missions)} missions to {self.storage_file}")

        except Exception as e:
            logger.error(f"Error saving missions: {e}")
            raise

    def load(self) -> None:
        """Load missions from disk with validation and migration."""
        if not os.path.exists(self.storage_file):
            self.missions = []
            logger.info(f"No existing missions file found, starting fresh")
            return

        lock = FileLock(self.lock_file, timeout=10)

        try:
            with lock:
                with open(self.storage_file, "r", encoding="utf-8") as f:
                    file_data = json.load(f)

                # Check if legacy format
                if is_legacy_format(file_data):
                    logger.info("Detected legacy format, migrating...")
                    file_data = migrate_from_legacy(file_data)
                    # Save migrated data
                    self.missions = file_data["missions"]
                    self.save()
                else:
                    # Validate new format
                    is_valid, error_msg = validate_missions_file(file_data)
                    if not is_valid:
                        logger.warning(f"Missions file validation failed: {error_msg}")
                        logger.warning("Attempting to load anyway with sanitization...")

                    self.missions = file_data.get("missions", [])

                # Sanitize all missions
                self.missions = [sanitize_mission(m) for m in self.missions]

                logger.info(f"Loaded {len(self.missions)} missions from {self.storage_file}")

        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error loading missions: {e}")
            logger.error("Starting with empty list. Check backups/ folder for recent backup.")
            self.missions = []
        except Exception as e:
            logger.error(f"Error loading missions: {e}, starting with empty list")
            self.missions = []

    def get_summary(self) -> Dict[str, Any]:
        """
        Get summary statistics about missions.

        Returns:
            Dict with counts and totals
        """
        active = [m for m in self.missions if m.get("status") == "active"]

        total_reward = sum(m.get("reward", 0) for m in active)
        total_scu = sum(
            sum(obj.get("scu_amount", 0) for obj in m.get("objectives", []))
            for m in active
        )

        return {
            "total_missions": len(self.missions),
            "active_missions": len(active),
            "total_reward": total_reward,
            "total_scu": total_scu
        }
