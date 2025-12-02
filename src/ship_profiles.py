"""
Ship profiles for Star Citizen hauling vessels.

Defines cargo capacity and constraints for different ships.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
from enum import Enum

from src.logger import get_logger

logger = get_logger()


class ShipManufacturer(Enum):
    """Ship manufacturers."""
    MISC = "MISC"
    CRUSADER = "Crusader Industries"
    RSI = "Roberts Space Industries"
    ARGO = "Argo Astronautics"
    DRAKE = "Drake Interplanetary"
    ANVIL = "Anvil Aerospace"
    ORIGIN = "Origin Jumpworks"


@dataclass
class ShipProfile:
    """
    Profile for a hauling ship.

    Contains cargo capacity and operational characteristics.
    """
    name: str
    manufacturer: ShipManufacturer
    cargo_capacity_scu: int
    cargo_hold_type: str  # "grid", "vehicle", "external"
    can_land_on_outposts: bool = True
    can_land_on_stations: bool = True
    quantum_fuel_capacity: int = 0  # For future fuel calculations
    crew_size: int = 1
    description: str = ""

    @property
    def display_name(self) -> str:
        """Full display name with manufacturer."""
        return f"{self.manufacturer.value} {self.name}"

    def can_handle_mission_scu(self, required_scu: int) -> bool:
        """
        Check if ship can handle required SCU.

        Args:
            required_scu: Required cargo capacity

        Returns:
            True if ship has enough capacity
        """
        return self.cargo_capacity_scu >= required_scu

    def get_capacity_percentage(self, current_scu: int) -> float:
        """
        Get current capacity usage as percentage.

        Args:
            current_scu: Current cargo load

        Returns:
            Percentage (0-100)
        """
        if self.cargo_capacity_scu == 0:
            return 0.0
        return (current_scu / self.cargo_capacity_scu) * 100


# Predefined ship profiles (common hauling ships)
SHIP_PROFILES: Dict[str, ShipProfile] = {
    # Small haulers
    "ARGO_RAFT": ShipProfile(
        name="RAFT",
        manufacturer=ShipManufacturer.ARGO,
        cargo_capacity_scu=192,
        cargo_hold_type="external",
        description="Compact single-seat cargo hauler with external cargo grid"
    ),
    "MISC_HULL_A": ShipProfile(
        name="Hull A",
        manufacturer=ShipManufacturer.MISC,
        cargo_capacity_scu=64,
        cargo_hold_type="external",
        description="Entry-level freighter for small-scale trading"
    ),
    "DRAKE_CUTLASS_BLACK": ShipProfile(
        name="Cutlass Black",
        manufacturer=ShipManufacturer.DRAKE,
        cargo_capacity_scu=46,
        cargo_hold_type="grid",
        description="Multi-role ship with decent cargo capacity"
    ),

    # Medium haulers
    "MISC_FREELANCER": ShipProfile(
        name="Freelancer",
        manufacturer=ShipManufacturer.MISC,
        cargo_capacity_scu=66,
        cargo_hold_type="grid",
        description="Versatile medium freighter"
    ),
    "MISC_FREELANCER_MAX": ShipProfile(
        name="Freelancer MAX",
        manufacturer=ShipManufacturer.MISC,
        cargo_capacity_scu=120,
        cargo_hold_type="grid",
        description="Maximized cargo variant of the Freelancer"
    ),
    "CRUSADER_MERCURY": ShipProfile(
        name="Mercury Star Runner",
        manufacturer=ShipManufacturer.CRUSADER,
        cargo_capacity_scu=114,
        cargo_hold_type="grid",
        description="Data runner with significant cargo capacity"
    ),
    "RSI_ZEUS_MK2_CL": ShipProfile(
        name="Zeus Mk II CL",
        manufacturer=ShipManufacturer.RSI,
        cargo_capacity_scu=128,
        cargo_hold_type="grid",
        description="Medium freight hauler cargo variant"
    ),
    "MISC_HULL_B": ShipProfile(
        name="Hull B",
        manufacturer=ShipManufacturer.MISC,
        cargo_capacity_scu=512,
        cargo_hold_type="external",
        description="Small-scale commercial freighter"
    ),

    # Large haulers
    "CRUSADER_C2_HERCULES": ShipProfile(
        name="C2 Hercules",
        manufacturer=ShipManufacturer.CRUSADER,
        cargo_capacity_scu=696,
        cargo_hold_type="vehicle",
        description="Heavy cargo lifter for vehicles and large cargo"
    ),
    "CRUSADER_M2_HERCULES": ShipProfile(
        name="M2 Hercules",
        manufacturer=ShipManufacturer.CRUSADER,
        cargo_capacity_scu=522,
        cargo_hold_type="vehicle",
        description="Military cargo transport"
    ),
    "MISC_HULL_C": ShipProfile(
        name="Hull C",
        manufacturer=ShipManufacturer.MISC,
        cargo_capacity_scu=4608,
        cargo_hold_type="external",
        can_land_on_outposts=False,  # Too large
        description="Large-scale commercial freighter"
    ),

    # Extra large haulers
    "MISC_HULL_D": ShipProfile(
        name="Hull D",
        manufacturer=ShipManufacturer.MISC,
        cargo_capacity_scu=6912,
        cargo_hold_type="external",
        can_land_on_outposts=False,
        can_land_on_stations=False,  # Requires station docking
        description="Capital-class bulk freighter"
    ),
    "MISC_HULL_E": ShipProfile(
        name="Hull E",
        manufacturer=ShipManufacturer.MISC,
        cargo_capacity_scu=12288,
        cargo_hold_type="external",
        can_land_on_outposts=False,
        can_land_on_stations=False,
        description="Super-freighter for massive cargo operations"
    ),
}


class ShipManager:
    """Manages ship profiles and selection."""

    def __init__(self):
        """Initialize with default ship profiles."""
        self.profiles = SHIP_PROFILES.copy()
        self.current_ship: Optional[str] = None

    def get_all_ships(self) -> List[ShipProfile]:
        """Get all available ship profiles."""
        return sorted(self.profiles.values(), key=lambda s: s.cargo_capacity_scu)

    def get_ship(self, ship_key: str) -> Optional[ShipProfile]:
        """
        Get a specific ship profile.

        Args:
            ship_key: Ship identifier key

        Returns:
            ShipProfile or None if not found
        """
        return self.profiles.get(ship_key)

    def set_current_ship(self, ship_key: str) -> bool:
        """
        Set the current active ship.

        Args:
            ship_key: Ship identifier key

        Returns:
            True if ship was found and set
        """
        if ship_key in self.profiles:
            self.current_ship = ship_key
            logger.info(f"Set current ship to {self.profiles[ship_key].display_name}")
            return True
        return False

    def get_current_ship(self) -> Optional[ShipProfile]:
        """Get the currently selected ship profile."""
        if self.current_ship:
            return self.profiles.get(self.current_ship)
        return None

    def get_ships_by_capacity(self, min_scu: int, max_scu: Optional[int] = None) -> List[ShipProfile]:
        """
        Get ships within a capacity range.

        Args:
            min_scu: Minimum cargo capacity
            max_scu: Maximum cargo capacity (None for no limit)

        Returns:
            List of matching ship profiles
        """
        ships = []
        for ship in self.profiles.values():
            if ship.cargo_capacity_scu >= min_scu:
                if max_scu is None or ship.cargo_capacity_scu <= max_scu:
                    ships.append(ship)

        return sorted(ships, key=lambda s: s.cargo_capacity_scu)

    def get_suitable_ships(self, required_scu: int) -> List[ShipProfile]:
        """
        Get ships that can handle the required SCU.

        Args:
            required_scu: Required cargo capacity

        Returns:
            List of suitable ships, sorted by capacity
        """
        return self.get_ships_by_capacity(min_scu=required_scu)

    def add_custom_ship(self, key: str, profile: ShipProfile) -> None:
        """
        Add a custom ship profile.

        Args:
            key: Unique identifier key
            profile: ShipProfile object
        """
        self.profiles[key] = profile
        logger.info(f"Added custom ship profile: {profile.display_name}")

    def get_ship_categories(self) -> Dict[str, List[ShipProfile]]:
        """
        Categorize ships by size.

        Returns:
            Dictionary mapping category name to list of ships
        """
        categories = {
            "Small (0-100 SCU)": [],
            "Medium (101-500 SCU)": [],
            "Large (501-5000 SCU)": [],
            "Extra Large (5000+ SCU)": []
        }

        for ship in self.profiles.values():
            if ship.cargo_capacity_scu <= 100:
                categories["Small (0-100 SCU)"].append(ship)
            elif ship.cargo_capacity_scu <= 500:
                categories["Medium (101-500 SCU)"].append(ship)
            elif ship.cargo_capacity_scu <= 5000:
                categories["Large (501-5000 SCU)"].append(ship)
            else:
                categories["Extra Large (5000+ SCU)"].append(ship)

        # Sort within each category
        for category in categories.values():
            category.sort(key=lambda s: s.cargo_capacity_scu)

        return categories
