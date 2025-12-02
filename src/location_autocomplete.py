"""
Location autocomplete with fuzzy matching.

Loads Star Citizen location data and provides filtered suggestions.
"""

import json
import os
from typing import List, Dict, Any


class LocationMatcher:
    """Provides fuzzy matching for Star Citizen locations."""

    def __init__(self, data_dir: str = "src/location_data") -> None:
        self.data_dir = data_dir
        self.all_locations: List[str] = []
        self.scannable_locations: List[str] = []  # Planets and stations only
        self.location_aliases: Dict[str, str] = {}  # alias -> canonical name
        self.load_locations()
        self._build_aliases()

    def load_locations(self) -> None:
        """Load all location names from JSON files."""
        self.all_locations = []
        self.scannable_locations = []

        # Load Stanton
        stanton_path = os.path.join(self.data_dir, "stanton.json")
        if os.path.exists(stanton_path):
            self._extract_locations_from_file(stanton_path)

        # Load Pyro
        pyro_path = os.path.join(self.data_dir, "pyro.json")
        if os.path.exists(pyro_path):
            self._extract_locations_from_file(pyro_path)

        # Load Nyx
        nyx_path = os.path.join(self.data_dir, "nyx.json")
        if os.path.exists(nyx_path):
            self._extract_locations_from_file(nyx_path)

        # Remove duplicates and sort
        self.all_locations = sorted(set(self.all_locations))
        self.scannable_locations = sorted(set(self.scannable_locations))

    def _extract_locations_from_file(self, filepath: str) -> None:
        """Extract all location names from a JSON file."""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Add planets (scannable)
            if "planets" in data:
                self.all_locations.extend(data["planets"])
                self.scannable_locations.extend(data["planets"])

            # Add moons (if it's a simple list) - scannable
            if "moons" in data and isinstance(data["moons"], list):
                self.all_locations.extend(data["moons"])
                self.scannable_locations.extend(data["moons"])

            # Add stations (scannable)
            if "stations" in data:
                if isinstance(data["stations"], list):
                    self.all_locations.extend(data["stations"])
                    self.scannable_locations.extend(data["stations"])
                elif isinstance(data["stations"], dict):
                    # Flatten categorized stations
                    for category, locations in data["stations"].items():
                        if isinstance(locations, list):
                            self.all_locations.extend(locations)
                            self.scannable_locations.extend(locations)

            # Add dropoffpoints (not scannable - these are outposts, etc.)
            if "dropoffpoints" in data:
                self._extract_from_nested(data["dropoffpoints"])

            # Add moon locations (not scannable - these are outposts on moons)
            if "moons" in data and isinstance(data["moons"], dict):
                self._extract_from_nested(data["moons"])

        except (json.JSONDecodeError, IOError) as e:
            print(f"Error loading location data from {filepath}: {e}")

    def _extract_from_nested(self, nested_dict: Dict[str, Any]) -> None:
        """Recursively extract location names from nested dictionaries."""
        for key, value in nested_dict.items():
            if isinstance(value, list):
                self.all_locations.extend(value)
            elif isinstance(value, dict):
                self._extract_from_nested(value)

    def fuzzy_match(self, query: str, limit: int = 10) -> List[str]:
        """
        Find locations matching the query using fuzzy matching.

        Args:
            query: Search string
            limit: Maximum number of results

        Returns:
            List of matching location names, sorted by relevance
        """
        if not query:
            return self.all_locations[:limit]

        query_lower = query.lower()
        matches = []

        for location in self.all_locations:
            location_lower = location.lower()

            # Exact match (highest priority)
            if location_lower == query_lower:
                matches.append((location, 0))
            # Starts with query (high priority)
            elif location_lower.startswith(query_lower):
                matches.append((location, 1))
            # Contains query (medium priority)
            elif query_lower in location_lower:
                matches.append((location, 2))
            # Word-level fuzzy match (lower priority)
            elif self._word_match(query_lower, location_lower):
                matches.append((location, 3))

        # Sort by priority, then alphabetically
        matches.sort(key=lambda x: (x[1], x[0]))

        return [match[0] for match in matches[:limit]]

    def _word_match(self, query: str, text: str) -> bool:
        """
        Check if all words in query appear in text.

        Args:
            query: Search query
            text: Text to search in

        Returns:
            True if all words in query are in text
        """
        query_words = query.split()
        return all(word in text for word in query_words)

    def get_all_locations(self) -> List[str]:
        """Get complete list of all locations."""
        return self.all_locations.copy()

    def get_scannable_locations(self) -> List[str]:
        """Get list of locations where missions can be scanned (planets/stations)."""
        return self.scannable_locations.copy()

    def get_locations_by_prefix(self, prefix: str, limit: int = 10) -> List[str]:
        """
        Get locations starting with prefix (case-insensitive).

        Args:
            prefix: Prefix to match
            limit: Maximum number of results

        Returns:
            List of matching location names
        """
        if not prefix:
            return self.all_locations[:limit]

        prefix_lower = prefix.lower()
        matches = [
            loc for loc in self.all_locations
            if loc.lower().startswith(prefix_lower)
        ]
        return matches[:limit]

    def _build_aliases(self) -> None:
        """Build alias mappings for location name variations."""
        import re

        # Pattern to match "above [Planet]" suffix
        above_pattern = re.compile(r'\s+above\s+\w+', re.IGNORECASE)

        # Pattern to match Lagrange station codes: XXX-LN Format
        lagrange_pattern = re.compile(r'^([A-Z]{3})-L(\d)\s+(.+)$', re.IGNORECASE)

        # Mapping of planet codes to full planet names
        planet_code_map = {
            'ARC': 'ArcCorp',
            'CRU': 'Crusader',
            'HUR': 'Hurston',
            'MIC': 'microTech'
        }

        for location in self.all_locations:
            # Canonical name is the full location name
            canonical = location

            # Create alias without "above X" suffix
            base_name = above_pattern.sub('', location).strip()
            if base_name != canonical:
                # Map both directions for matching
                self.location_aliases[base_name.lower()] = canonical
                self.location_aliases[canonical.lower()] = canonical

            # Handle Lagrange station aliases
            lagrange_match = lagrange_pattern.match(location)
            if lagrange_match:
                planet_code = lagrange_match.group(1).upper()
                lagrange_num = lagrange_match.group(2)
                station_name = lagrange_match.group(3)

                # Get full planet name
                planet_name = planet_code_map.get(planet_code, planet_code)

                # Create descriptive alias: "Station Name at Planet's LN Lagrange point"
                descriptive_alias = f"{station_name} at {planet_name}'s L{lagrange_num} Lagrange point"
                self.location_aliases[descriptive_alias.lower()] = canonical

                # Also map just the station name to canonical
                self.location_aliases[station_name.lower()] = canonical

                # Map the code prefix version: "MIC-L1"
                code_prefix = f"{planet_code}-L{lagrange_num}"
                self.location_aliases[code_prefix.lower()] = canonical

            # Also map the canonical name to itself (normalized)
            self.location_aliases[canonical.lower()] = canonical

    def normalize_location(self, location: str) -> str:
        """
        Normalize a location name to its canonical form.

        Handles variations like:
        - "Baijini Point" -> "Baijini Point above ArcCorp"
        - "Baijini Point above ArcCorp" -> "Baijini Point above ArcCorp"
        - "baijini point" -> "Baijini Point above ArcCorp"

        Args:
            location: Location name (any variation)

        Returns:
            Canonical location name, or original if no match found
        """
        if not location:
            return location

        # Try exact match first
        location_lower = location.strip().lower()

        # Check if we have an alias mapping
        if location_lower in self.location_aliases:
            return self.location_aliases[location_lower]

        # No match found, return original
        return location.strip()

    def get_best_match(self, location: str, confidence_threshold: int = 2) -> str:
        """
        Find the best matching location name using fuzzy matching.

        This method is useful for autocorrecting potentially OCR-extracted
        or typo-prone location names to their canonical forms.

        Args:
            location: Location name to match
            confidence_threshold: Maximum match priority to accept (0=exact, 1=starts-with, 2=contains, 3=word-match)
                                 Lower values require higher confidence matches.

        Returns:
            Best matching location name, or original if no good match found
        """
        if not location:
            return location

        location = location.strip()
        location_lower = location.lower()

        # First try alias normalization (fastest)
        if location_lower in self.location_aliases:
            return self.location_aliases[location_lower]

        # Collect all matches with their priorities
        matches = []

        for loc in self.all_locations:
            loc_lower = loc.lower()

            # Exact match (priority 0 - highest)
            if loc_lower == location_lower:
                matches.append((loc, 0))
            # Starts with query (priority 1)
            elif loc_lower.startswith(location_lower):
                matches.append((loc, 1))
            # Contains query (priority 2)
            elif location_lower in loc_lower:
                matches.append((loc, 2))
            # Word-level match (priority 3)
            elif self._word_match(location_lower, loc_lower):
                matches.append((loc, 3))

        # Filter by confidence threshold and sort by priority
        valid_matches = [(loc, priority) for loc, priority in matches if priority <= confidence_threshold]

        if valid_matches:
            # Sort by priority (lower is better), then alphabetically
            valid_matches.sort(key=lambda x: (x[1], x[0]))
            return valid_matches[0][0]

        # No match found, return original
        return location
