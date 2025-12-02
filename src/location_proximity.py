"""
Location proximity system for Star Citizen.

Understands spatial relationships between locations based on planetary systems.
"""

import re
from typing import Dict, List, Set, Optional


class LocationProximity:
    """Calculates proximity between Star Citizen locations."""

    def __init__(self):
        # Map location to its planetary system info
        self.location_to_system: Dict[str, Dict] = {}
        self._build_relationships()

    def _build_relationships(self):
        """Build location relationship mappings."""
        # Pattern to extract planet from "above X" stations
        above_pattern = re.compile(r'above\s+(\w+)', re.IGNORECASE)

        # Pattern to extract planet from moon locations (e.g., "on Lyria")
        on_moon_pattern = re.compile(r'on\s+(\w+)', re.IGNORECASE)

        # Pattern for Lagrange stations (e.g., "ARC-L1", "MIC-L2")
        lagrange_pattern = re.compile(r'([A-Z]{3})-L(\d+)', re.IGNORECASE)

        # Known planetary systems (simplified - can be expanded)
        self.planet_systems = {
            # Stanton system
            "ArcCorp": {"code": "ARC", "moons": ["Lyria", "Wala"]},
            "Hurston": {"code": "HUR", "moons": ["Aberdeen", "Aerial", "Magda", "Ita"]},
            "microTech": {"code": "MIC", "moons": ["Calliope", "Clio", "Euterpe"]},
            "Crusader": {"code": "CRU", "moons": ["Cellin", "Daymar", "Yela"]},
            # Nyx system
            "Delamar": {"code": None, "moons": []},  # Asteroid, no Lagrange points
        }

    def get_proximity_group(self, location: str) -> Dict[str, any]:
        """
        Get proximity grouping info for a location.

        Returns dict with:
        - planet: Associated planet name
        - type: 'planet', 'above_planet', 'moon', 'L1_L2', 'L3_plus', 'gateway', 'other'
        - proximity_tier: 0 (same location), 1 (narrow - planet/moons), 2 (wide - L1/L2), 3 (far)
        """
        # Check for "above X" stations
        above_match = re.search(r'above\s+(\w+)', location, re.IGNORECASE)
        if above_match:
            planet = above_match.group(1)
            if planet in self.planet_systems:
                return {"planet": planet, "type": "above_planet", "proximity_tier": 1}

        # Check for Lagrange stations
        lagrange_match = re.search(r'([A-Z]{3})-L(\d+)', location, re.IGNORECASE)
        if lagrange_match:
            code = lagrange_match.group(1).upper()
            lagrange_num = int(lagrange_match.group(2))

            # Find planet by code
            for planet, info in self.planet_systems.items():
                if info["code"] == code:
                    if lagrange_num <= 2:
                        return {"planet": planet, "type": "L1_L2", "proximity_tier": 2}
                    else:
                        return {"planet": planet, "type": "L3_plus", "proximity_tier": 3}

        # Check if location mentions a moon
        for planet, info in self.planet_systems.items():
            for moon in info["moons"]:
                if moon.lower() in location.lower():
                    return {"planet": planet, "type": "moon", "proximity_tier": 1}

        # Check if location is the planet itself
        for planet in self.planet_systems.keys():
            if planet.lower() in location.lower():
                return {"planet": planet, "type": "planet", "proximity_tier": 1}

        # Check for gateways
        if "gateway" in location.lower() or "gate" in location.lower():
            return {"planet": None, "type": "gateway", "proximity_tier": 3}

        # Unknown/other
        return {"planet": None, "type": "other", "proximity_tier": 3}

    def calculate_proximity(self, loc1: str, loc2: str) -> int:
        """
        Calculate proximity score between two locations.

        Lower score = closer proximity
        0 = same location
        1 = same narrow group (planet + moons + above station)
        2 = same wide group (includes L1/L2)
        3 = far (different planets, L3+, gateways)
        """
        if loc1.lower() == loc2.lower():
            return 0

        info1 = self.get_proximity_group(loc1)
        info2 = self.get_proximity_group(loc2)

        # If both have a planet association
        if info1["planet"] and info2["planet"]:
            if info1["planet"] == info2["planet"]:
                # Same planet system
                max_tier = max(info1["proximity_tier"], info2["proximity_tier"])
                if max_tier == 1:
                    return 1  # Narrow group
                elif max_tier == 2:
                    return 2  # Wide group
            else:
                return 3  # Different planets

        # At least one has no planet association (gateway, other)
        return 3

    def sort_locations_by_proximity(self, locations: List[str], start_location: str) -> List[str]:
        """
        Sort locations by proximity to start location.

        Args:
            locations: List of location names to sort
            start_location: Starting location

        Returns:
            Sorted list with closest locations first
        """
        def proximity_key(loc):
            return self.calculate_proximity(start_location, loc)

        # Sort by proximity, then alphabetically
        return sorted(locations, key=lambda loc: (proximity_key(loc), loc))

    def group_locations_by_proximity(self, locations: List[str], start_location: str) -> Dict[str, List[str]]:
        """
        Group locations by their proximity to start location.

        Returns dict with keys:
        - 'narrow': Same planet/moons/above station
        - 'wide': Same system L1/L2
        - 'far': Other planets, L3+, gateways
        """
        groups = {
            "current": [],  # Start location itself
            "narrow": [],   # Proximity 1
            "wide": [],     # Proximity 2
            "far": []       # Proximity 3
        }

        for loc in locations:
            proximity = self.calculate_proximity(start_location, loc)
            if proximity == 0:
                groups["current"].append(loc)
            elif proximity == 1:
                groups["narrow"].append(loc)
            elif proximity == 2:
                groups["wide"].append(loc)
            else:
                groups["far"].append(loc)

        return groups
