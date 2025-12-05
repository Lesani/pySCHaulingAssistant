"""
Location hierarchy for intelligent distance estimation.

Since precise travel times aren't possible (rotating universe), we use
hierarchical proximity scoring: same station < same moon < same planet < same system.
"""

from typing import Dict, Optional, Tuple
from enum import IntEnum
import re

from src.logger import get_logger

logger = get_logger()


class LocationLevel(IntEnum):
    """Hierarchy levels for locations."""
    UNKNOWN = 0
    STATION = 1  # Specific station/outpost
    MOON = 2     # Moon orbit
    PLANET = 3   # Planet orbit
    LAGRANGE = 4 # Lagrange points
    SYSTEM = 5   # System-level


class ProximityWeight(IntEnum):
    """Proximity weights for route planning (lower = closer)."""
    SAME_STATION = 1      # Same exact location
    SAME_MOON = 2         # Same moon (different stations)
    SAME_PLANET = 3       # Same planet (different moons)
    SAME_LAGRANGE = 4     # Nearby Lagrange point
    SAME_SYSTEM = 5       # Same system (different planets)
    DIFFERENT_SYSTEM = 10 # Different star system


class LocationHierarchy:
    """
    Manages location hierarchy and proximity calculations.

    Parses location names to extract hierarchical information.
    """

    def __init__(self):
        """Initialize with Star Citizen location patterns."""
        # Common patterns in SC location names
        self.station_patterns = [
            r"(.+?)\s+(?:Station|Outpost|Mining Facility|Rest Stop)",
            r"(.+?)\s+(?:SAL|SAT|SMO|SHI|SPK)-\d+",  # Mining facilities
            r"Port\s+(.+)",
            r"(.+?)\s+above\s+(.+)",  # e.g., "Baijini Point above ArcCorp"
        ]

        # Known celestial bodies - Stanton system
        self.stanton_planets = ["Hurston", "ArcCorp", "microTech", "Crusader"]
        self.stanton_moons = {
            "Hurston": ["Aberdeen", "Magda", "Arial", "Ita"],
            "ArcCorp": ["Lyria", "Wala"],
            "microTech": ["Calliope", "Clio", "Euterpe"],
            "Crusader": ["Cellin", "Daymar", "Yela"]
        }

        # Known celestial bodies - Nyx system
        self.nyx_planets = ["Delamar"]  # Asteroid treated as planet
        self.nyx_moons = {}

        # Known celestial bodies - Pyro system
        self.pyro_planets = ["Pyro 1", "Monox", "Bloom", "Pyro IV", "Pyro V", "Terminus"]
        self.pyro_moons = {
            "Pyro V": ["Ignis", "Vatra", "Adir", "Fairo", "Fuego", "Vuur"]
        }

        # All planets combined
        self.all_planets = self.stanton_planets + self.nyx_planets + self.pyro_planets
        self.all_moons = {**self.stanton_moons, **self.nyx_moons, **self.pyro_moons}

        # Lagrange points
        self.lagrange_pattern = r"(HUR|ARC|MIC|CRU)L-?\d+"

    def parse_location(self, location: str) -> Tuple[str, Optional[str], Optional[str]]:
        """
        Parse location into components: (station, celestial_body, parent_body).

        Args:
            location: Location string

        Returns:
            Tuple of (station_name, moon/planet, parent_planet)
        """
        location = location.strip()

        # Check for "X above Y" pattern
        above_match = re.search(r"(.+?)\s+above\s+(.+)", location, re.IGNORECASE)
        if above_match:
            station = above_match.group(1).strip()
            body = above_match.group(2).strip()
            parent = self._find_parent_body(body)
            return station, body, parent

        # Check for "on Moon" pattern
        on_match = re.search(r"(.+?)\s+on\s+(.+)", location, re.IGNORECASE)
        if on_match:
            station = on_match.group(1).strip()
            body = on_match.group(2).strip()
            parent = self._find_parent_body(body)
            return station, body, parent

        # Check if it's a planet or moon directly
        if location in self.all_planets:
            return location, location, None

        for planet, moons in self.all_moons.items():
            if location in moons:
                return location, location, planet

        # Check for Lagrange point
        if re.match(self.lagrange_pattern, location):
            return location, location, None

        # Default: treat as station name, try to extract body from name
        body = self._extract_body_from_name(location)
        parent = self._find_parent_body(body) if body else None
        return location, body, parent

    def _find_parent_body(self, body: str) -> Optional[str]:
        """Find parent planet for a moon."""
        if not body:
            return None

        for planet, moons in self.all_moons.items():
            if body in moons:
                return planet
        return None

    def _extract_body_from_name(self, location: str) -> Optional[str]:
        """Try to extract celestial body from location name."""
        # Check for planet names in location
        for planet in self.all_planets:
            if planet.lower() in location.lower():
                return planet

        # Check for moon names
        for planet, moons in self.all_moons.items():
            for moon in moons:
                if moon.lower() in location.lower():
                    return moon

        return None

    def _get_system(self, body: Optional[str], parent: Optional[str]) -> Optional[str]:
        """Determine which star system a body belongs to."""
        # Check direct body or parent
        check_body = parent if parent else body
        if not check_body:
            return None

        # Check Stanton system
        if check_body in self.stanton_planets:
            return "Stanton"

        # Check Nyx system
        if check_body in self.nyx_planets:
            return "Nyx"

        # Check Pyro system
        if check_body in self.pyro_planets:
            return "Pyro"

        # Check moons
        for planet in self.stanton_moons:
            if check_body in self.stanton_moons[planet]:
                return "Stanton"
        for planet in self.pyro_moons:
            if check_body in self.pyro_moons[planet]:
                return "Pyro"

        return None

    def get_system_for_location(self, location: str) -> Optional[str]:
        """
        Determine which system a location belongs to.

        Args:
            location: Location name string

        Returns:
            System name (Stanton, Nyx, Pyro) or None if unknown
        """
        if not location:
            return None

        # Parse the location
        _, body, parent = self.parse_location(location)

        # Try internal method first
        system = self._get_system(body, parent)
        if system:
            return system

        # Try pattern matching on the location name
        loc_lower = location.lower()

        # Stanton indicators
        stanton_patterns = [
            "hurston", "arccorp", "microtech", "crusader",
            "lorville", "area 18", "orison", "new babbage",
            "hur-", "arc-", "mic-", "cru-",
            "aberdeen", "arial", "magda", "ita",
            "lyria", "wala",
            "calliope", "clio", "euterpe",
            "cellin", "daymar", "yela",
            "everus", "baijini", "seraphim", "tressler",
            "grimm hex", "grim hex"
        ]

        for pattern in stanton_patterns:
            if pattern in loc_lower:
                return "Stanton"

        # Nyx indicators
        if "delamar" in loc_lower or "levski" in loc_lower:
            return "Nyx"
        if "nyx gateway" in loc_lower or "stanton gateway" in loc_lower:
            return "Nyx"

        # Pyro indicators
        pyro_patterns = [
            "pyro", "ruin station", "orbituary", "patch city",
            "checkmate", "endgame", "gaslight",
            "monox", "bloom", "terminus", "ignis", "vatra"
        ]

        for pattern in pyro_patterns:
            if pattern in loc_lower:
                return "Pyro"

        return None

    def estimate_route_distance(self, locations: list[str]) -> float:
        """
        Estimate total route distance using proximity weights.

        Sums the proximity weights between consecutive locations.

        Args:
            locations: Ordered list of location names

        Returns:
            Total estimated distance (sum of proximity weights)
        """
        if len(locations) < 2:
            return 0.0

        total = 0.0
        for i in range(len(locations) - 1):
            weight = self.calculate_proximity_weight(locations[i], locations[i + 1])
            total += weight

        return total

    def calculate_proximity_weight(self, loc1: str, loc2: str) -> int:
        """
        Calculate proximity weight between two locations.

        Lower weight = closer locations.

        Args:
            loc1: First location
            loc2: Second location

        Returns:
            Proximity weight (1-10)
        """
        # Same location
        if loc1 == loc2:
            return ProximityWeight.SAME_STATION

        # Parse both locations
        station1, body1, parent1 = self.parse_location(loc1)
        station2, body2, parent2 = self.parse_location(loc2)

        # Same celestial body (different stations)
        if body1 and body2 and body1 == body2:
            return ProximityWeight.SAME_MOON

        # Same parent planet (different moons)
        if parent1 and parent2 and parent1 == parent2:
            return ProximityWeight.SAME_PLANET

        # Check if both in same system (Stanton, Nyx, etc.)
        body1_system = self._get_system(body1, parent1)
        body2_system = self._get_system(body2, parent2)

        if body1_system and body2_system and body1_system == body2_system:
            return ProximityWeight.SAME_SYSTEM

        # Different systems (or unknown)
        return ProximityWeight.DIFFERENT_SYSTEM

    def sort_by_proximity(
        self,
        current_location: str,
        candidate_locations: list[str]
    ) -> list[Tuple[str, int]]:
        """
        Sort locations by proximity to current location.

        Args:
            current_location: Starting location
            candidate_locations: List of locations to sort

        Returns:
            List of (location, weight) tuples, sorted by weight (closest first)
        """
        weighted = [
            (loc, self.calculate_proximity_weight(current_location, loc))
            for loc in candidate_locations
        ]

        return sorted(weighted, key=lambda x: x[1])

    def find_nearest_location(
        self,
        current_location: str,
        candidate_locations: list[str]
    ) -> Optional[str]:
        """
        Find the nearest location from candidates.

        Args:
            current_location: Starting location
            candidate_locations: List of locations to consider

        Returns:
            Nearest location or None if no candidates
        """
        if not candidate_locations:
            return None

        sorted_locs = self.sort_by_proximity(current_location, candidate_locations)
        return sorted_locs[0][0]

    def group_locations_by_proximity(
        self,
        locations: list[str]
    ) -> Dict[str, list[str]]:
        """
        Group locations by celestial body.

        Args:
            locations: List of location names

        Returns:
            Dictionary mapping body name to locations on that body
        """
        groups = {}

        for location in locations:
            _, body, parent = self.parse_location(location)

            # Use body as key, or parent if no body
            key = body or parent or "Unknown"

            if key not in groups:
                groups[key] = []
            groups[key].append(location)

        return groups

    def is_same_celestial_body(self, loc1: str, loc2: str) -> bool:
        """Check if two locations are on the same celestial body."""
        _, body1, _ = self.parse_location(loc1)
        _, body2, _ = self.parse_location(loc2)
        return body1 and body2 and body1 == body2

    def get_location_description(self, location: str) -> str:
        """
        Get a hierarchical description of a location.

        Args:
            location: Location name

        Returns:
            Formatted description
        """
        station, body, parent = self.parse_location(location)

        parts = [station]
        if body and body != station:
            parts.append(f"on {body}")
        if parent:
            parts.append(f"({parent} system)")

        return " ".join(parts)
