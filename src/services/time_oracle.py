"""
Star Citizen Time Oracle for Travel Time Estimation

Models travel time between locations accounting for:
- Quantum drive spooling
- Travel to quantum gate
- Quantum travel
- Exit from quantum
- Atmospheric entry/descent
- Approach and landing
- Terminal/pad access

Uses cached median times with exponential smoothing for online corrections.
"""

import json
import os
from typing import Dict, Tuple, Optional
from dataclasses import dataclass, field
from enum import Enum


class LocationType(Enum):
    """Types of locations in Star Citizen"""
    SPACE_STATION = "space_station"  # Orbital stations (Port Olisar, etc.)
    LAGRANGE_STATION = "lagrange"    # L1-L5 stations
    PLANETARY_OUTPOST = "outpost"     # Surface outposts
    PLANETARY_CITY = "city"           # Major landing zones (Lorville, Area 18)
    DISTRIBUTION_CENTER = "distro"    # Distribution centers
    MINING_FACILITY = "mining"        # Mining facilities
    UNKNOWN = "unknown"


@dataclass
class TravelTimeComponents:
    """Breakdown of travel time components (all in minutes)"""
    spool: float = 0.0          # QT spool time
    to_qt_gate: float = 0.0     # Travel to QT departure point
    quantum: float = 0.0        # Quantum travel time
    exit_qt: float = 0.0        # QT exit to approach
    atmosphere: float = 0.0     # Atmospheric entry/descent
    approach: float = 0.0       # Final approach to pad
    landing: float = 0.0        # Landing sequence
    terminal: float = 0.0       # Pad to terminal/cargo area
    service: float = 0.0        # Service time at location

    @property
    def total(self) -> float:
        """Total travel time in minutes"""
        return (self.spool + self.to_qt_gate + self.quantum + self.exit_qt +
                self.atmosphere + self.approach + self.landing + self.terminal +
                self.service)


@dataclass
class LocationInfo:
    """Information about a location for travel time calculation"""
    name: str
    location_type: LocationType
    parent_body: Optional[str] = None  # Planet/moon if applicable
    has_atmosphere: bool = False
    pad_type: str = "small"  # small, medium, large, hangar


class TimeOracle:
    """
    Calculates travel times between Star Citizen locations.

    Uses heuristic-based estimation with caching and exponential smoothing
    for learning actual times.
    """

    # Service time constants (minutes)
    SERVICE_TIMES = {
        LocationType.SPACE_STATION: 2.0,
        LocationType.LAGRANGE_STATION: 2.0,
        LocationType.PLANETARY_OUTPOST: 3.0,
        LocationType.PLANETARY_CITY: 5.0,
        LocationType.DISTRIBUTION_CENTER: 2.5,
        LocationType.MINING_FACILITY: 2.5,
        LocationType.UNKNOWN: 3.0,
    }

    # Base travel time components (minutes)
    BASE_SPOOL_TIME = 0.25  # 15 seconds
    BASE_TO_QT_GATE = 1.0   # 1 minute to leave vicinity
    BASE_EXIT_QT = 0.5      # 30 seconds from QT exit to approach
    BASE_APPROACH = 1.0     # 1 minute approach time
    BASE_LANDING = 0.5      # 30 seconds landing
    BASE_TERMINAL = 0.5     # 30 seconds pad to terminal

    # Atmospheric entry times by planet type
    ATMO_ENTRY_TIMES = {
        "thin": 2.0,    # Moons with thin atmosphere
        "normal": 4.0,  # Standard planets
        "thick": 6.0,   # Dense atmosphere planets
    }

    def __init__(self, cache_file: str = "travel_time_cache.json"):
        """
        Initialize time oracle with optional cache file.

        Args:
            cache_file: Path to JSON file for caching travel times
        """
        self.cache_file = cache_file
        self.travel_cache: Dict[Tuple[str, str], float] = {}
        self.location_cache: Dict[str, LocationInfo] = {}
        self.smoothing_alpha = 0.3  # Weight for new observations

        self._load_cache()
        self._init_location_database()

    def _load_cache(self):
        """Load cached travel times from file"""
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r') as f:
                    data = json.load(f)
                    # Convert string keys back to tuples
                    self.travel_cache = {
                        tuple(k.split('|')): v
                        for k, v in data.items()
                    }
            except Exception as e:
                print(f"Warning: Could not load travel time cache: {e}")

    def _save_cache(self):
        """Save travel times to cache file"""
        try:
            # Convert tuple keys to strings for JSON
            cache_data = {
                f"{k[0]}|{k[1]}": v
                for k, v in self.travel_cache.items()
            }
            with open(self.cache_file, 'w') as f:
                json.dump(cache_data, f, indent=2)
        except Exception as e:
            print(f"Warning: Could not save travel time cache: {e}")

    def _init_location_database(self):
        """Initialize location type database from location data"""
        # Load location data from all systems
        location_data_dir = os.path.join(
            os.path.dirname(__file__),
            '..', 'location_data'
        )

        # Load all system files (Stanton, Pyro, Nyx)
        for system_file in ['stanton.json', 'pyro.json', 'nyx.json']:
            location_data_path = os.path.join(location_data_dir, system_file)
            if os.path.exists(location_data_path):
                try:
                    with open(location_data_path, 'r') as f:
                        data = json.load(f)
                        self._categorize_locations(data)
                except Exception as e:
                    print(f"Warning: Could not load {system_file}: {e}")

    def _categorize_locations(self, data: dict):
        """Categorize locations by type"""
        stations = data.get('stations', {})

        # Space stations
        for station in stations.get('Stations', []):
            self.location_cache[station.lower()] = LocationInfo(
                name=station,
                location_type=LocationType.SPACE_STATION,
                has_atmosphere=False
            )

        # Lagrange stations
        for station in stations.get('Lagrange Stations', []):
            self.location_cache[station.lower()] = LocationInfo(
                name=station,
                location_type=LocationType.LAGRANGE_STATION,
                has_atmosphere=False
            )

        # Distribution centers
        for center in stations.get('Distribution Centers', []):
            # Determine if it's on a planet/moon
            is_surface = any(planet in center for planet in data.get('planets', []))
            self.location_cache[center.lower()] = LocationInfo(
                name=center,
                location_type=LocationType.DISTRIBUTION_CENTER,
                has_atmosphere=is_surface
            )

        # Cities from dropoffpoints
        dropoffpoints = data.get('dropoffpoints', {})
        for planet_or_moon, categories in dropoffpoints.items():
            cities = categories.get('City', [])
            for city in cities:
                self.location_cache[city.lower()] = LocationInfo(
                    name=city,
                    location_type=LocationType.PLANETARY_CITY,
                    has_atmosphere=True
                )

    def get_location_info(self, location_name: str) -> LocationInfo:
        """
        Get or infer location information.

        Args:
            location_name: Name of the location

        Returns:
            LocationInfo object
        """
        key = location_name.lower()

        if key in self.location_cache:
            return self.location_cache[key]

        # Infer type from name
        name_lower = location_name.lower()

        if any(x in name_lower for x in ['station', 'harbor', 'port', 'tressler']):
            loc_type = LocationType.SPACE_STATION
            has_atmo = False
        elif any(x in name_lower for x in ['-l1', '-l2', '-l3', '-l4', '-l5', 'lagrange']):
            loc_type = LocationType.LAGRANGE_STATION
            has_atmo = False
        elif any(x in name_lower for x in ['outpost', 'settlement']):
            loc_type = LocationType.PLANETARY_OUTPOST
            has_atmo = True
        elif any(x in name_lower for x in ['lorville', 'area 18', 'new babbage', 'orison', 'levski']):
            loc_type = LocationType.PLANETARY_CITY
            has_atmo = True
        elif 'mining' in name_lower:
            loc_type = LocationType.MINING_FACILITY
            # Mining facilities can be on surface or in space
            has_atmo = any(x in name_lower for x in ['lyria', 'wala', 'daymar', 'yela', 'cellin'])
        elif any(x in name_lower for x in ['distribution', 'logistics']):
            loc_type = LocationType.DISTRIBUTION_CENTER
            has_atmo = True  # Most are on surface
        else:
            loc_type = LocationType.UNKNOWN
            has_atmo = False

        return LocationInfo(
            name=location_name,
            location_type=loc_type,
            has_atmosphere=has_atmo
        )

    def calculate_quantum_time(self, from_loc: LocationInfo, to_loc: LocationInfo) -> float:
        """
        Estimate quantum travel time between locations.

        Uses heuristics based on location types:
        - Same planet/moon: 2-5 minutes
        - Nearby bodies: 5-10 minutes
        - Cross-system: 10-20 minutes

        Args:
            from_loc: Origin location
            to_loc: Destination location

        Returns:
            Estimated quantum travel time in minutes
        """
        # Check if we have cached actual time
        cache_key = (from_loc.name, to_loc.name)
        if cache_key in self.travel_cache:
            return self.travel_cache[cache_key]

        # Heuristic estimation based on location types
        from_type = from_loc.location_type
        to_type = to_loc.location_type

        # Same location = no QT
        if from_loc.name.lower() == to_loc.name.lower():
            return 0.0

        # Both on same planet/moon
        if (from_loc.parent_body and to_loc.parent_body and
            from_loc.parent_body == to_loc.parent_body):
            return 3.0  # Local QT

        # Station to station (different orbits)
        if (from_type in [LocationType.SPACE_STATION, LocationType.LAGRANGE_STATION] and
            to_type in [LocationType.SPACE_STATION, LocationType.LAGRANGE_STATION]):
            return 8.0

        # Station to surface or vice versa
        if ((from_type in [LocationType.SPACE_STATION, LocationType.LAGRANGE_STATION] and
             to_loc.has_atmosphere) or
            (to_type in [LocationType.SPACE_STATION, LocationType.LAGRANGE_STATION] and
             from_loc.has_atmosphere)):
            return 6.0

        # Surface to surface on different bodies
        if from_loc.has_atmosphere and to_loc.has_atmosphere:
            return 12.0

        # Default cross-system travel
        return 10.0

    def calculate_travel_time(
        self,
        from_location: str,
        to_location: str,
        departure_time: Optional[int] = None
    ) -> TravelTimeComponents:
        """
        Calculate complete travel time breakdown between locations.

        Args:
            from_location: Origin location name
            to_location: Destination location name
            departure_time: Optional departure time (for future time-aware routing)

        Returns:
            TravelTimeComponents with detailed breakdown
        """
        from_info = self.get_location_info(from_location)
        to_info = self.get_location_info(to_location)

        components = TravelTimeComponents()

        # Same location = just service time
        if from_location.lower() == to_location.lower():
            components.service = self.SERVICE_TIMES[to_info.location_type]
            return components

        # Spool time (always needed for QT)
        components.spool = self.BASE_SPOOL_TIME

        # Travel to QT gate (depends on origin type)
        if from_info.has_atmosphere:
            components.to_qt_gate = 3.0  # Longer to leave atmosphere
        else:
            components.to_qt_gate = self.BASE_TO_QT_GATE

        # Quantum travel
        components.quantum = self.calculate_quantum_time(from_info, to_info)

        # Exit QT
        components.exit_qt = self.BASE_EXIT_QT

        # Atmospheric entry (if destination has atmosphere)
        if to_info.has_atmosphere:
            if to_info.location_type == LocationType.PLANETARY_CITY:
                components.atmosphere = self.ATMO_ENTRY_TIMES["thick"]
            else:
                components.atmosphere = self.ATMO_ENTRY_TIMES["normal"]

        # Approach
        if to_info.location_type == LocationType.PLANETARY_CITY:
            components.approach = 2.0  # Cities have longer approach
        else:
            components.approach = self.BASE_APPROACH

        # Landing
        components.landing = self.BASE_LANDING

        # Terminal access
        if to_info.location_type == LocationType.PLANETARY_CITY:
            components.terminal = 1.0  # Cities have longer terminal access
        else:
            components.terminal = self.BASE_TERMINAL

        # Service time
        components.service = self.SERVICE_TIMES[to_info.location_type]

        return components

    def get_travel_time(
        self,
        from_location: str,
        to_location: str,
        departure_time: Optional[int] = None
    ) -> float:
        """
        Get total travel time between locations.

        Args:
            from_location: Origin location name
            to_location: Destination location name
            departure_time: Optional departure time (for future use)

        Returns:
            Total travel time in minutes
        """
        components = self.calculate_travel_time(from_location, to_location, departure_time)
        return components.total

    def update_actual_time(
        self,
        from_location: str,
        to_location: str,
        actual_time: float
    ):
        """
        Update cache with actual observed travel time using exponential smoothing.

        Args:
            from_location: Origin location name
            to_location: Destination location name
            actual_time: Actual travel time observed (minutes)
        """
        cache_key = (from_location, to_location)

        if cache_key in self.travel_cache:
            # Exponential smoothing: new_value = α * actual + (1-α) * cached
            cached = self.travel_cache[cache_key]
            self.travel_cache[cache_key] = (
                self.smoothing_alpha * actual_time +
                (1 - self.smoothing_alpha) * cached
            )
        else:
            # First observation
            self.travel_cache[cache_key] = actual_time

        self._save_cache()

    def get_distance_matrix(self, locations: list[str]) -> Dict[Tuple[str, str], float]:
        """
        Build a distance (time) matrix for a set of locations.

        Args:
            locations: List of location names

        Returns:
            Dictionary mapping (from, to) pairs to travel times
        """
        matrix = {}

        for i, from_loc in enumerate(locations):
            for j, to_loc in enumerate(locations):
                if i == j:
                    matrix[(from_loc, to_loc)] = 0.0
                else:
                    matrix[(from_loc, to_loc)] = self.get_travel_time(from_loc, to_loc)

        return matrix


# Global time oracle instance
_time_oracle_instance: Optional[TimeOracle] = None


def get_time_oracle() -> TimeOracle:
    """Get or create the global time oracle instance"""
    global _time_oracle_instance
    if _time_oracle_instance is None:
        _time_oracle_instance = TimeOracle()
    return _time_oracle_instance
