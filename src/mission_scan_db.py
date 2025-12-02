"""
Mission scan database for storing scanned missions with location data.

Stores all scanned missions regardless of whether they are added to the hauling list.
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Any, Optional
from uuid import uuid4
from filelock import FileLock

from src.logger import get_logger

logger = get_logger()


class MissionScanDB:
    """Database for storing scanned missions with location and timestamp."""

    def __init__(self, storage_file: str = "mission_scans.json") -> None:
        self.storage_file = storage_file
        self.lock_file = storage_file + ".lock"
        self.scans: List[Dict[str, Any]] = []
        self.load()

    def add_scan(
        self,
        mission_data: Dict[str, Any],
        scan_location: Optional[str] = None
    ) -> str:
        """
        Add a scanned mission to the database.

        Args:
            mission_data: Dict with reward, availability, objectives
            scan_location: Where the mission was scanned (planet/station)

        Returns:
            Scan ID (UUID)
        """
        scan_id = str(uuid4())

        scan_record = {
            "id": scan_id,
            "scan_timestamp": datetime.now().isoformat(),
            "scan_location": scan_location,
            "mission_data": mission_data
        }

        self.scans.append(scan_record)
        self.save()

        logger.info(
            f"Added scan {scan_id[:8]} at location: {scan_location or 'No Location'}"
        )
        return scan_id

    def get_scans(
        self,
        location: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Get scanned missions, optionally filtered by location.

        Args:
            location: Filter by scan location (None for all)
            limit: Maximum number of results (None for all)

        Returns:
            List of scan records, most recent first
        """
        results = self.scans.copy()

        if location is not None:
            results = [s for s in results if s.get("scan_location") == location]

        # Sort by timestamp descending (most recent first)
        results.sort(key=lambda x: x.get("scan_timestamp", ""), reverse=True)

        if limit is not None:
            results = results[:limit]

        return results

    def get_scan(self, scan_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific scan by ID.

        Args:
            scan_id: UUID of the scan

        Returns:
            Scan record or None if not found
        """
        for scan in self.scans:
            if scan["id"] == scan_id:
                return scan.copy()
        return None

    def delete_scan(self, scan_id: str) -> bool:
        """
        Delete a scan from the database.

        Args:
            scan_id: UUID of the scan

        Returns:
            True if deleted, False if not found
        """
        for i, scan in enumerate(self.scans):
            if scan["id"] == scan_id:
                del self.scans[i]
                self.save()
                return True
        return False

    def update_scan_location(self, scan_id: str, new_location: str) -> bool:
        """
        Update the location of a scan.

        Args:
            scan_id: UUID of the scan
            new_location: New location value

        Returns:
            True if updated, False if not found
        """
        for scan in self.scans:
            if scan["id"] == scan_id:
                scan["scan_location"] = new_location
                scan["synced"] = False  # Mark as unsynced so it gets re-uploaded
                self.save()
                logger.info(f"Updated scan {scan_id[:8]} location to: {new_location}")
                return True
        return False

    def mark_scan_synced(self, scan_id: str) -> bool:
        """
        Mark a scan as synced.

        Args:
            scan_id: UUID of the scan

        Returns:
            True if updated, False if not found
        """
        for scan in self.scans:
            if scan["id"] == scan_id:
                scan["synced"] = True
                self.save()
                return True
        return False

    def is_scan_synced(self, scan_id: str) -> bool:
        """
        Check if a scan has been synced.

        Args:
            scan_id: UUID of the scan

        Returns:
            True if synced, False if not synced or not found
        """
        for scan in self.scans:
            if scan["id"] == scan_id:
                return scan.get("synced", False)
        return False

    def get_locations_with_scans(self) -> List[str]:
        """
        Get list of all locations that have scans.

        Returns:
            List of location names
        """
        locations = set()
        for scan in self.scans:
            loc = scan.get("scan_location")
            if loc:
                locations.add(loc)
        return sorted(locations)

    def get_summary(self) -> Dict[str, Any]:
        """
        Get summary statistics about scans.

        Returns:
            Dict with counts and location breakdown
        """
        location_counts: Dict[str, int] = {}
        for scan in self.scans:
            loc = scan.get("scan_location") or "No Location"
            location_counts[loc] = location_counts.get(loc, 0) + 1

        return {
            "total_scans": len(self.scans),
            "locations": location_counts
        }

    def save(self) -> None:
        """Save scans to disk with file locking."""
        lock = FileLock(self.lock_file, timeout=10)

        try:
            with lock:
                file_data = {
                    "version": "1.0",
                    "scans": self.scans
                }

                with open(self.storage_file, "w", encoding="utf-8") as f:
                    json.dump(file_data, f, indent=2)

                logger.debug(f"Saved {len(self.scans)} scans to {self.storage_file}")

        except Exception as e:
            logger.error(f"Error saving scans: {e}")
            raise

    def load(self) -> None:
        """Load scans from disk."""
        if not os.path.exists(self.storage_file):
            self.scans = []
            logger.info("No existing scans file found, starting fresh")
            return

        lock = FileLock(self.lock_file, timeout=10)

        try:
            with lock:
                with open(self.storage_file, "r", encoding="utf-8") as f:
                    file_data = json.load(f)

                self.scans = file_data.get("scans", [])
                logger.info(f"Loaded {len(self.scans)} scans from {self.storage_file}")

        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error loading scans: {e}")
            self.scans = []
        except Exception as e:
            logger.error(f"Error loading scans: {e}, starting with empty list")
            self.scans = []
