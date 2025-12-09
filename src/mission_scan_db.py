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
from src.special_locations import (
    is_interstellar_location,
    get_system_from_special_location
)
from src.location_hierarchy import LocationHierarchy

logger = get_logger()

# Canonical contractor names and their aliases (lowercase keys)
CONTRACTOR_CANONICAL = {
    "Covalex Shipping": [
        "covalex shipping",
        "covalex",
        "covalex independent contractors",
    ],
    "Ling Family Hauling": [
        "ling family hauling",
        "ling family",
        "ling hauling",
    ],
    "Red Wind Linehaul": [
        "red wind linehaul",
        "red wind",
        "redwind",
    ],
}

# Build reverse lookup: alias -> canonical
_CONTRACTOR_ALIAS_MAP = {}
for canonical, aliases in CONTRACTOR_CANONICAL.items():
    for alias in aliases:
        _CONTRACTOR_ALIAS_MAP[alias] = canonical


def normalize_contractor(contracted_by: str) -> str:
    """
    Normalize a contractor name to its canonical form.

    Handles OCR errors and variations like "Covalex" -> "Covalex Shipping".

    Args:
        contracted_by: Raw contractor name from scan

    Returns:
        Canonical contractor name, or original if unknown
    """
    if not contracted_by:
        return ""

    lower = contracted_by.lower().strip()

    # Exact alias match
    if lower in _CONTRACTOR_ALIAS_MAP:
        return _CONTRACTOR_ALIAS_MAP[lower]

    # Prefix match - check if input starts with a known company name
    for alias, canonical in _CONTRACTOR_ALIAS_MAP.items():
        # Check if the first word matches
        first_word = lower.split()[0] if lower.split() else ""
        alias_first = alias.split()[0] if alias.split() else ""
        if first_word and alias_first and first_word == alias_first:
            return canonical

    # No match - return original (trimmed)
    return contracted_by.strip()


class MissionScanDB:
    """Database for storing scanned missions with location and timestamp."""

    def __init__(self, storage_file: str = "mission_scans.json") -> None:
        self.storage_file = storage_file
        self.lock_file = storage_file + ".lock"
        self.scans: List[Dict[str, Any]] = []
        self._location_hierarchy = LocationHierarchy()
        self.load()

    def _get_mission_identity(self, mission_data: Dict[str, Any]) -> tuple:
        """
        Create a hashable identity tuple for mission comparison.

        Identity is based on reward, contracted_by (normalized), and objectives.

        Args:
            mission_data: Dict containing mission fields

        Returns:
            Tuple that uniquely identifies the mission content
        """
        reward = mission_data.get("reward", 0)
        contracted_by = normalize_contractor(mission_data.get("contracted_by", ""))

        # Normalize objectives to sorted tuple of tuples
        objectives = mission_data.get("objectives", [])
        obj_tuples = []
        for obj in objectives:
            obj_tuple = (
                obj.get("cargo_type", ""),
                obj.get("scu_amount", 0),
                obj.get("collect_from", ""),
                obj.get("deliver_to", "")
            )
            obj_tuples.append(obj_tuple)

        # Sort for consistent ordering
        sorted_objectives = tuple(sorted(obj_tuples))

        return (reward, contracted_by, sorted_objectives)

    def _find_duplicate_scan(
        self,
        mission_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Find an existing scan with identical mission data.

        Args:
            mission_data: Mission data to match

        Returns:
            Existing scan record if found, None otherwise
        """
        new_identity = self._get_mission_identity(mission_data)

        for scan in self.scans:
            existing_identity = self._get_mission_identity(
                scan.get("mission_data", {})
            )
            if existing_identity == new_identity:
                return scan

        return None

    def _consolidate_locations(
        self,
        existing_locations: List[str],
        new_location: Optional[str]
    ) -> List[str]:
        """
        Consolidate locations with interstellar rules.

        Rules:
        1. If adding "INTERSTELLAR (X)", remove all specific locations from
           system X and replace with just the interstellar tag
        2. If existing has "INTERSTELLAR (X)" for system X, don't add
           specific locations from system X
        3. Different systems accumulate their locations normally

        Args:
            existing_locations: Current list of locations
            new_location: New location to potentially add

        Returns:
            Updated list of locations
        """
        if not new_location:
            return existing_locations

        # Start with a copy
        locations = list(existing_locations)

        # Check if new location is already present
        if new_location in locations:
            return locations

        # Determine the system of the new location
        if is_interstellar_location(new_location):
            new_system = get_system_from_special_location(new_location)
        else:
            new_system = self._location_hierarchy.get_system_for_location(
                new_location
            )

        # Check if we're adding an interstellar location
        if is_interstellar_location(new_location) and new_system:
            # Remove all specific locations from this system
            filtered = []
            for loc in locations:
                if is_interstellar_location(loc):
                    # Keep interstellar tags from other systems
                    loc_system = get_system_from_special_location(loc)
                    if loc_system != new_system:
                        filtered.append(loc)
                else:
                    # Keep locations from other systems
                    loc_system = self._location_hierarchy.get_system_for_location(
                        loc
                    )
                    if loc_system != new_system:
                        filtered.append(loc)
            locations = filtered
            locations.append(new_location)
        else:
            # Adding a specific location - check for existing interstellar
            has_interstellar_for_system = False
            if new_system:
                for loc in locations:
                    if is_interstellar_location(loc):
                        loc_system = get_system_from_special_location(loc)
                        if loc_system == new_system:
                            has_interstellar_for_system = True
                            break

            if not has_interstellar_for_system:
                locations.append(new_location)

        return locations

    def add_scan(
        self,
        mission_data: Dict[str, Any],
        scan_location: Optional[str] = None
    ) -> str:
        """
        Add a scanned mission to the database, with deduplication.

        If an identical mission exists, adds the location to existing record
        instead of creating a new scan.

        Args:
            mission_data: Dict with reward, availability, objectives
            scan_location: Where the mission was scanned (planet/station)

        Returns:
            Scan ID (existing or new UUID)
        """
        # Normalize contractor name before processing
        if "contracted_by" in mission_data:
            original = mission_data["contracted_by"]
            normalized = normalize_contractor(original)
            if normalized != original:
                logger.debug(f"Normalized contractor: '{original}' -> '{normalized}'")
                mission_data["contracted_by"] = normalized

        # Check for duplicate
        existing_scan = self._find_duplicate_scan(mission_data)

        if existing_scan:
            # Update existing scan with new location
            existing_locations = existing_scan.get("scan_locations", [])
            new_locations = self._consolidate_locations(
                existing_locations,
                scan_location
            )

            if new_locations != existing_locations:
                existing_scan["scan_locations"] = new_locations
                existing_scan["synced"] = False  # Mark for re-sync
                self.save()
                logger.info(
                    f"Added location '{scan_location}' to existing scan "
                    f"{existing_scan['id'][:8]} ({len(new_locations)} locations)"
                )
            else:
                logger.info(
                    f"Location '{scan_location}' already tracked for scan "
                    f"{existing_scan['id'][:8]}"
                )

            return existing_scan["id"]

        # Create new scan
        scan_id = str(uuid4())
        locations = [scan_location] if scan_location else []

        scan_record = {
            "id": scan_id,
            "scan_timestamp": datetime.now().isoformat(),
            "scan_locations": locations,
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
            results = [
                s for s in results
                if location in s.get("scan_locations", [])
            ]

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
        Update the location of a scan (replaces all locations with single one).

        For backward compatibility. Consider using set_scan_locations() or
        add_location_to_scan() instead.

        Args:
            scan_id: UUID of the scan
            new_location: New location value

        Returns:
            True if updated, False if not found
        """
        return self.set_scan_locations(scan_id, [new_location] if new_location else [])

    def set_scan_locations(
        self,
        scan_id: str,
        locations: List[str]
    ) -> bool:
        """
        Replace all locations for a scan.

        Args:
            scan_id: UUID of the scan
            locations: New list of locations

        Returns:
            True if updated, False if not found
        """
        for scan in self.scans:
            if scan["id"] == scan_id:
                scan["scan_locations"] = locations
                scan["synced"] = False
                self.save()
                logger.info(
                    f"Updated scan {scan_id[:8]} locations to: {locations}"
                )
                return True
        return False

    def add_location_to_scan(self, scan_id: str, location: str) -> bool:
        """
        Add a location to a scan's location list with consolidation.

        Applies interstellar consolidation rules.

        Args:
            scan_id: UUID of the scan
            location: Location to add

        Returns:
            True if updated, False if not found
        """
        for scan in self.scans:
            if scan["id"] == scan_id:
                existing = scan.get("scan_locations", [])
                new_locations = self._consolidate_locations(existing, location)

                if new_locations != existing:
                    scan["scan_locations"] = new_locations
                    scan["synced"] = False
                    self.save()
                    logger.info(
                        f"Added location '{location}' to scan {scan_id[:8]}"
                    )
                return True
        return False

    def remove_location_from_scan(self, scan_id: str, location: str) -> bool:
        """
        Remove a location from a scan's location list.

        Args:
            scan_id: UUID of the scan
            location: Location to remove

        Returns:
            True if updated, False if not found or location not present
        """
        for scan in self.scans:
            if scan["id"] == scan_id:
                locations = scan.get("scan_locations", [])
                if location in locations:
                    locations.remove(location)
                    scan["scan_locations"] = locations
                    scan["synced"] = False
                    self.save()
                    logger.info(
                        f"Removed location '{location}' from scan {scan_id[:8]}"
                    )
                    return True
                return False
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

    def deduplicate_existing(self) -> int:
        """
        Scan database for duplicates and merge them.

        First normalizes contractor names, then groups scans by mission identity,
        keeps the one with earliest timestamp, merges all locations, and removes
        the duplicates.

        Returns:
            Count of duplicates removed
        """
        # Normalize contractors first (this affects identity matching)
        self.normalize_contractors()

        # Group scans by identity
        identity_groups: Dict[tuple, List[Dict[str, Any]]] = {}

        for scan in self.scans:
            identity = self._get_mission_identity(scan.get("mission_data", {}))
            if identity not in identity_groups:
                identity_groups[identity] = []
            identity_groups[identity].append(scan)

        # Find groups with duplicates
        duplicates_removed = 0
        ids_to_remove = set()

        for identity, group in identity_groups.items():
            if len(group) <= 1:
                continue  # No duplicates

            # Sort by timestamp to keep the earliest
            group.sort(key=lambda x: x.get("scan_timestamp", ""))
            canonical = group[0]

            # Merge locations from all duplicates into the canonical
            all_locations = set(canonical.get("scan_locations", []))
            for duplicate in group[1:]:
                for loc in duplicate.get("scan_locations", []):
                    if loc:
                        all_locations.add(loc)
                ids_to_remove.add(duplicate["id"])
                duplicates_removed += 1

            canonical["scan_locations"] = list(all_locations)
            canonical["synced"] = False  # Mark for re-sync

        # Remove duplicates
        if ids_to_remove:
            self.scans = [s for s in self.scans if s["id"] not in ids_to_remove]
            self.save()
            logger.info(f"Deduplicated {duplicates_removed} scans")

        return duplicates_removed

    def normalize_contractors(self) -> int:
        """
        Normalize all contractor names in existing scans.

        Updates scans with non-canonical contractor names and marks them
        for re-sync so the corrected values are uploaded.

        Returns:
            Count of scans that were normalized
        """
        normalized_count = 0

        for scan in self.scans:
            mission_data = scan.get("mission_data", {})
            if "contracted_by" not in mission_data:
                continue

            original = mission_data["contracted_by"]
            normalized = normalize_contractor(original)

            if normalized != original:
                mission_data["contracted_by"] = normalized
                scan["synced"] = False  # Mark for re-sync
                normalized_count += 1
                logger.debug(f"Normalized contractor: '{original}' -> '{normalized}'")

        if normalized_count > 0:
            self.save()
            logger.info(f"Normalized {normalized_count} contractor names")

        return normalized_count

    def get_locations_with_scans(self) -> List[str]:
        """
        Get list of all locations that have scans.

        Returns:
            List of location names
        """
        locations = set()
        for scan in self.scans:
            for loc in scan.get("scan_locations", []):
                if loc:
                    locations.add(loc)
        return sorted(locations)

    def query_scans(
        self,
        min_reward: Optional[float] = None,
        max_reward: Optional[float] = None,
        ranks: Optional[List[str]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Query scans with multiple filter criteria.

        Args:
            min_reward: Minimum reward value (inclusive)
            max_reward: Maximum reward value (inclusive)
            ranks: List of acceptable ranks (None for all)
            limit: Maximum number of results

        Returns:
            List of scan records matching criteria, most recent first
        """
        results = []

        for scan in self.scans:
            mission_data = scan.get("mission_data", {})

            # Filter by reward
            reward = mission_data.get("reward", 0)
            if min_reward is not None and reward < min_reward:
                continue
            if max_reward is not None and reward > max_reward:
                continue

            # Filter by rank
            if ranks is not None:
                scan_rank = mission_data.get("rank")
                if scan_rank and scan_rank not in ranks:
                    continue

            results.append(scan)

        # Sort by timestamp descending
        results.sort(key=lambda x: x.get("scan_timestamp", ""), reverse=True)

        if limit is not None:
            results = results[:limit]

        return results

    def get_unique_ranks(self) -> List[str]:
        """
        Get list of all unique ranks found in scans.

        Returns:
            List of rank names, ordered by hierarchy
        """
        # Define rank order
        rank_order = [
            "Trainee", "Rookie", "Junior", "Member",
            "Experienced", "Senior", "Master"
        ]

        found_ranks = set()
        for scan in self.scans:
            mission_data = scan.get("mission_data", {})
            rank = mission_data.get("rank")
            if rank:
                found_ranks.add(rank)

        # Return in hierarchy order
        return [r for r in rank_order if r in found_ranks]

    def get_unique_contractors(self) -> List[str]:
        """
        Get list of all unique contracted_by values.

        Returns:
            List of contractor names, sorted alphabetically
        """
        contractors = set()
        for scan in self.scans:
            mission_data = scan.get("mission_data", {})
            contractor = mission_data.get("contracted_by")
            if contractor:
                contractors.add(contractor)
        return sorted(contractors)

    def get_summary(self) -> Dict[str, Any]:
        """
        Get summary statistics about scans.

        Returns:
            Dict with counts and location breakdown
        """
        location_counts: Dict[str, int] = {}
        for scan in self.scans:
            locations = scan.get("scan_locations", [])
            if not locations:
                location_counts["No Location"] = location_counts.get(
                    "No Location", 0
                ) + 1
            else:
                for loc in locations:
                    location_counts[loc] = location_counts.get(loc, 0) + 1

        return {
            "total_scans": len(self.scans),
            "locations": location_counts
        }

    def _migrate_v1_to_v2(self, file_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Migrate version 1.0 data to version 2.0.

        Converts scan_location (string) to scan_locations (list).

        Args:
            file_data: V1 file data

        Returns:
            V2 file data
        """
        scans = file_data.get("scans", [])

        for scan in scans:
            # Convert scan_location to scan_locations
            old_location = scan.pop("scan_location", None)
            if old_location:
                scan["scan_locations"] = [old_location]
            else:
                scan["scan_locations"] = []

        file_data["version"] = "2.0"
        logger.info(f"Migrated {len(scans)} scans from v1.0 to v2.0")
        return file_data

    def save(self) -> None:
        """Save scans to disk with file locking."""
        lock = FileLock(self.lock_file, timeout=10)

        try:
            with lock:
                file_data = {
                    "version": "2.0",
                    "scans": self.scans
                }

                with open(self.storage_file, "w", encoding="utf-8") as f:
                    json.dump(file_data, f, indent=2)

                logger.debug(f"Saved {len(self.scans)} scans to {self.storage_file}")

        except Exception as e:
            logger.error(f"Error saving scans: {e}")
            raise

    def load(self) -> None:
        """Load scans from disk, migrating if necessary."""
        if not os.path.exists(self.storage_file):
            self.scans = []
            logger.info("No existing scans file found, starting fresh")
            return

        lock = FileLock(self.lock_file, timeout=10)

        try:
            with lock:
                with open(self.storage_file, "r", encoding="utf-8") as f:
                    file_data = json.load(f)

                # Check version and migrate if needed
                version = file_data.get("version", "1.0")
                if version == "1.0":
                    file_data = self._migrate_v1_to_v2(file_data)
                    # Save migrated data
                    with open(self.storage_file, "w", encoding="utf-8") as f:
                        json.dump(file_data, f, indent=2)

                self.scans = file_data.get("scans", [])
                logger.info(f"Loaded {len(self.scans)} scans from {self.storage_file}")

        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error loading scans: {e}")
            self.scans = []
        except Exception as e:
            logger.error(f"Error loading scans: {e}, starting with empty list")
            self.scans = []
