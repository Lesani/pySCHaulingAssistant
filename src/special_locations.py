"""
Special locations for Star Citizen multi-system support.

Defines system-specific interstellar locations and jump points.
"""

# Available star systems (as of Alpha 4.4)
SYSTEMS = ["Stanton", "Pyro", "Nyx"]

# System-specific interstellar locations
# Used when player is in transit within a system's interstellar space
INTERSTELLAR_LOCATIONS = [
    "INTERSTELLAR (Stanton)",
    "INTERSTELLAR (Pyro)",
    "INTERSTELLAR (Nyx)",
]

# Jump points between systems
# Format: "System1-System2 Jump Point (CurrentSystem)"
# Each jump point exists in both systems it connects
JUMP_POINTS = [
    # Stanton jump points
    "Stanton-Pyro Jump Point (Stanton)",
    "Stanton-Nyx Jump Point (Stanton)",
    # Pyro jump points
    "Pyro-Stanton Jump Point (Pyro)",
    "Pyro-Nyx Jump Point (Pyro)",
    # Nyx jump points
    "Nyx-Stanton Jump Point (Nyx)",
    "Nyx-Pyro Jump Point (Nyx)",
]

# All special locations combined (for adding to location dropdowns)
SPECIAL_LOCATIONS = INTERSTELLAR_LOCATIONS + JUMP_POINTS

# UI Constants
NO_LOCATION_TEXT = "-- No Location --"


def get_system_from_special_location(location: str) -> str | None:
    """
    Extract the system from a special location string.

    Args:
        location: Location string like "INTERSTELLAR (Stanton)" or
                  "Stanton-Pyro Jump Point (Stanton)"

    Returns:
        System name or None if not a special location
    """
    if not location:
        return None

    # Check interstellar locations
    for system in SYSTEMS:
        if f"INTERSTELLAR ({system})" in location:
            return system

    # Check jump points - system is in parentheses at the end
    if "Jump Point" in location:
        for system in SYSTEMS:
            if location.endswith(f"({system})"):
                return system

    return None


def is_interstellar_location(location: str) -> bool:
    """Check if location is an interstellar location."""
    return location in INTERSTELLAR_LOCATIONS or location == "INTERSTELLAR"


def is_jump_point(location: str) -> bool:
    """Check if location is a jump point."""
    return location in JUMP_POINTS or "Jump Point" in location


def is_special_location(location: str) -> bool:
    """Check if location is any special location (interstellar or jump point)."""
    return is_interstellar_location(location) or is_jump_point(location)


def get_jump_point_destination(location: str) -> str | None:
    """
    Get the destination system for a jump point.

    Args:
        location: Jump point location string

    Returns:
        Destination system name or None
    """
    if not is_jump_point(location):
        return None

    # Parse "System1-System2 Jump Point (CurrentSystem)"
    # The destination is the system that's NOT in the parentheses
    current_system = get_system_from_special_location(location)
    if not current_system:
        return None

    # Extract systems from the name
    for system in SYSTEMS:
        if system in location and system != current_system:
            return system

    return None
