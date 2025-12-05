"""
Location type classifier for Route Finder.

Classifies locations into detailed types (orbital station, lagrange, city, etc.)
and determines which star system they belong to.
"""

import json
import os
import re
from typing import Dict, List, Optional
from dataclasses import dataclass

from src.logger import get_logger

logger = get_logger()


class LocationType:
    """Location type constants."""
    ORBITAL_STATION = "orbital_station"
    LAGRANGE_STATION = "lagrange_station"
    DISTRIBUTION_CENTER = "distribution_center"
    CITY = "city"
    OUTPOST = "outpost"
    MINING_FACILITY = "mining_facility"
    SCRAPYARD = "scrapyard"
    FARMING_OUTPOST = "farming_outpost"
    UNKNOWN = "unknown"

    # Display names for UI
    DISPLAY_NAMES = {
        ORBITAL_STATION: "Orbital Stations",
        LAGRANGE_STATION: "Lagrange Stations",
        DISTRIBUTION_CENTER: "Distribution Centers",
        CITY: "Cities",
        OUTPOST: "Outposts",
        MINING_FACILITY: "Mining Facilities",
        SCRAPYARD: "Scrapyards",
        FARMING_OUTPOST: "Farming Outposts",
        UNKNOWN: "Unknown",
    }

    @classmethod
    def all_types(cls) -> List[str]:
        """Return all valid location types."""
        return [
            cls.ORBITAL_STATION,
            cls.LAGRANGE_STATION,
            cls.DISTRIBUTION_CENTER,
            cls.CITY,
            cls.OUTPOST,
            cls.MINING_FACILITY,
            cls.SCRAPYARD,
            cls.FARMING_OUTPOST,
        ]

    @classmethod
    def space_only_types(cls) -> List[str]:
        """Return types that are in space (not planetside)."""
        return [
            cls.ORBITAL_STATION,
            cls.LAGRANGE_STATION,
            cls.DISTRIBUTION_CENTER,
        ]

    @classmethod
    def ground_types(cls) -> List[str]:
        """Return types that are on the ground (planetside)."""
        return [
            cls.CITY,
            cls.OUTPOST,
            cls.MINING_FACILITY,
            cls.SCRAPYARD,
            cls.FARMING_OUTPOST,
        ]


@dataclass
class LocationInfo:
    """Information about a location."""
    name: str
    location_type: str
    system: str
    celestial_body: Optional[str] = None


class LocationTypeClassifier:
    """
    Classifies locations into detailed types using location_data JSON files.

    Loads location data from stanton.json, nyx.json, pyro.json and builds
    a mapping from location name to type and system.
    """

    # Mapping from JSON category names to LocationType constants
    CATEGORY_MAP = {
        "stations": LocationType.ORBITAL_STATION,
        "lagrange stations": LocationType.LAGRANGE_STATION,
        "distribution centers": LocationType.DISTRIBUTION_CENTER,
        "distribution center": LocationType.DISTRIBUTION_CENTER,
        "city": LocationType.CITY,
        "outpost": LocationType.OUTPOST,
        "mining facility": LocationType.MINING_FACILITY,
        "scrapyard": LocationType.SCRAPYARD,
        "farming outpost": LocationType.FARMING_OUTPOST,
    }

    def __init__(self, data_dir: str = None):
        """
        Initialize the classifier.

        Args:
            data_dir: Path to location_data directory. If None, uses default.
        """
        if data_dir is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            data_dir = os.path.join(base_dir, "src", "location_data")

        self.data_dir = data_dir
        self._location_map: Dict[str, LocationInfo] = {}
        self._locations_by_type: Dict[str, List[str]] = {t: [] for t in LocationType.all_types()}
        self._locations_by_system: Dict[str, List[str]] = {}

        self._load_all_data()

    def _load_all_data(self) -> None:
        """Load all location data files."""
        systems = [
            ("stanton.json", "Stanton"),
            ("nyx.json", "Nyx"),
            ("pyro.json", "Pyro"),
        ]

        for filename, system_name in systems:
            filepath = os.path.join(self.data_dir, filename)
            if os.path.exists(filepath):
                self._load_system_data(filepath, system_name)
            else:
                logger.warning(f"Location data file not found: {filepath}")

        logger.info(f"Loaded {len(self._location_map)} locations across {len(self._locations_by_system)} systems")

    def _load_system_data(self, filepath: str, system_name: str) -> None:
        """Load location data for a single system."""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.error(f"Error loading {filepath}: {e}")
            return

        if system_name not in self._locations_by_system:
            self._locations_by_system[system_name] = []

        # Parse stations section (dict with category keys)
        stations = data.get("stations", {})
        if isinstance(stations, dict):
            for category, locations in stations.items():
                if isinstance(locations, list):
                    loc_type = self._category_to_type(category)
                    for loc in locations:
                        self._add_location(loc, loc_type, system_name)

        # Parse dropoffpoints section
        dropoffpoints = data.get("dropoffpoints", {})
        for body_name, body_data in dropoffpoints.items():
            if isinstance(body_data, dict):
                for category, locations in body_data.items():
                    if isinstance(locations, list):
                        loc_type = self._category_to_type(category)
                        for loc in locations:
                            self._add_location(loc, loc_type, system_name, body_name)

        # Parse moons section (nested: Planet -> Moon -> Category -> Locations)
        moons = data.get("moons", {})
        if isinstance(moons, dict):
            for planet_name, planet_moons in moons.items():
                if isinstance(planet_moons, dict):
                    for moon_name, moon_data in planet_moons.items():
                        if isinstance(moon_data, dict):
                            for category, locations in moon_data.items():
                                if isinstance(locations, list):
                                    loc_type = self._category_to_type(category)
                                    for loc in locations:
                                        self._add_location(loc, loc_type, system_name, moon_name)

    def _category_to_type(self, category: str) -> str:
        """Convert a category name from JSON to a LocationType constant."""
        return self.CATEGORY_MAP.get(category.lower(), LocationType.OUTPOST)

    def _add_location(
        self,
        name: str,
        loc_type: str,
        system: str,
        celestial_body: str = None
    ) -> None:
        """Add a location to the mappings."""
        normalized = self._normalize_name(name)

        info = LocationInfo(
            name=name,
            location_type=loc_type,
            system=system,
            celestial_body=celestial_body
        )

        self._location_map[normalized] = info
        self._locations_by_type[loc_type].append(name)
        self._locations_by_system[system].append(name)

    def _normalize_name(self, name: str) -> str:
        """Normalize location name for consistent lookup."""
        return " ".join(name.lower().split())

    def classify_location(self, location: str) -> str:
        """
        Classify a location into a type.

        Args:
            location: Location name

        Returns:
            LocationType constant
        """
        if not location:
            return LocationType.UNKNOWN

        normalized = self._normalize_name(location)

        # Direct lookup
        if normalized in self._location_map:
            return self._location_map[normalized].location_type

        # Fallback to pattern matching
        return self._classify_by_pattern(location)

    def _classify_by_pattern(self, location: str) -> str:
        """Classify location by name patterns when not found in data."""
        loc_lower = location.lower()

        # Lagrange pattern: XXX-L1, HUR-L2, etc.
        if re.search(r"[a-z]{3}-?l\d", loc_lower):
            return LocationType.LAGRANGE_STATION

        # Distribution centers
        if "distribution" in loc_lower or "logistics depot" in loc_lower:
            return LocationType.DISTRIBUTION_CENTER

        # Mining facilities
        if "mining" in loc_lower or "shubin" in loc_lower:
            return LocationType.MINING_FACILITY

        # Scrapyards/Salvage
        if "salvage" in loc_lower or "scrap" in loc_lower or "breaker" in loc_lower:
            return LocationType.SCRAPYARD

        # Farming
        if "farm" in loc_lower or "hydro" in loc_lower:
            return LocationType.FARMING_OUTPOST

        # Cities
        if any(city in loc_lower for city in ["lorville", "area 18", "orison", "levski", "new babbage", "nb int"]):
            return LocationType.CITY

        # Orbital stations
        if "station" in loc_lower or "harbor" in loc_lower or "point" in loc_lower or "gateway" in loc_lower:
            return LocationType.ORBITAL_STATION

        # Spaceports are cities
        if "spaceport" in loc_lower:
            return LocationType.CITY

        # HDMS prefix is outpost
        if loc_lower.startswith("hdms"):
            return LocationType.OUTPOST

        return LocationType.OUTPOST

    def get_system_for_location(self, location: str) -> Optional[str]:
        """
        Determine which system a location belongs to.

        Args:
            location: Location name

        Returns:
            System name (Stanton, Nyx, Pyro) or None if unknown
        """
        if not location:
            return None

        normalized = self._normalize_name(location)

        # Direct lookup
        if normalized in self._location_map:
            return self._location_map[normalized].system

        # Fallback to pattern inference
        return self._infer_system(location)

    def _infer_system(self, location: str) -> Optional[str]:
        """Infer system from location name patterns."""
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

    def get_location_info(self, location: str) -> Optional[LocationInfo]:
        """Get full location info."""
        if not location:
            return None
        normalized = self._normalize_name(location)
        return self._location_map.get(normalized)

    def get_locations_by_type(self, location_type: str) -> List[str]:
        """Get all locations of a specific type."""
        return self._locations_by_type.get(location_type, [])

    def get_locations_by_system(self, system: str) -> List[str]:
        """Get all locations in a system."""
        return self._locations_by_system.get(system, [])

    def get_all_systems(self) -> List[str]:
        """Get list of all known systems."""
        return list(self._locations_by_system.keys())

    def is_space_location(self, location: str) -> bool:
        """Check if location is in space (not planetside)."""
        loc_type = self.classify_location(location)
        return loc_type in LocationType.space_only_types()

    def is_ground_location(self, location: str) -> bool:
        """Check if location is on the ground (planetside)."""
        loc_type = self.classify_location(location)
        return loc_type in LocationType.ground_types()
