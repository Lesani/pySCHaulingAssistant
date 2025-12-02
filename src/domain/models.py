"""
Core domain models for hauling missions.

Clean data classes representing business entities.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any
from uuid import uuid4


class MissionStatus(Enum):
    """Mission status enumeration."""
    ACTIVE = "active"
    COMPLETED = "completed"
    EXPIRED = "expired"


@dataclass
class Objective:
    """
    A single cargo objective within a mission.

    Represents picking up cargo from one location and delivering to another.
    """
    collect_from: str
    deliver_to: str
    scu_amount: int
    cargo_type: str = "Unknown"
    mission_id: Optional[str] = None  # ID of parent mission (for tracking completions)

    def __post_init__(self):
        """Validate objective data."""
        if not self.collect_from:
            raise ValueError("collect_from cannot be empty")
        if not self.deliver_to:
            raise ValueError("deliver_to cannot be empty")
        if self.scu_amount <= 0:
            raise ValueError(f"scu_amount must be positive, got {self.scu_amount}")
        if not self.cargo_type:
            self.cargo_type = "Unknown"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "collect_from": self.collect_from,
            "deliver_to": self.deliver_to,
            "scu_amount": self.scu_amount,
            "cargo_type": self.cargo_type,
            "mission_id": self.mission_id
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Objective':
        """Create from dictionary."""
        return cls(
            collect_from=data["collect_from"],
            deliver_to=data["deliver_to"],
            scu_amount=data["scu_amount"],
            cargo_type=data.get("cargo_type", "Unknown"),
            mission_id=data.get("mission_id")
        )


@dataclass
class Mission:
    """
    A hauling mission with objectives and metadata.

    Core business entity representing a hauling contract.
    """
    reward: float
    availability: str  # HH:MM:SS format or "N/A"
    objectives: List[Objective]
    id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    status: MissionStatus = MissionStatus.ACTIVE

    def __post_init__(self):
        """Validate mission data."""
        if self.reward <= 0:
            raise ValueError(f"reward must be positive, got {self.reward}")
        if not self.objectives:
            raise ValueError("mission must have at least one objective")

        # Convert status string to enum if needed
        if isinstance(self.status, str):
            self.status = MissionStatus(self.status)

    @property
    def total_scu(self) -> int:
        """Total SCU across all objectives."""
        return sum(obj.scu_amount for obj in self.objectives)

    @property
    def source_locations(self) -> List[str]:
        """Unique source locations."""
        return list(set(obj.collect_from for obj in self.objectives))

    @property
    def destination_locations(self) -> List[str]:
        """Unique destination locations."""
        return list(set(obj.deliver_to for obj in self.objectives))

    @property
    def is_active(self) -> bool:
        """Check if mission is active."""
        return self.status == MissionStatus.ACTIVE

    def mark_completed(self) -> None:
        """Mark mission as completed."""
        self.status = MissionStatus.COMPLETED

    def mark_expired(self) -> None:
        """Mark mission as expired."""
        self.status = MissionStatus.EXPIRED

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "status": self.status.value,
            "reward": self.reward,
            "availability": self.availability,
            "objectives": [obj.to_dict() for obj in self.objectives]
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Mission':
        """Create from dictionary."""
        objectives = [Objective.from_dict(obj) for obj in data["objectives"]]
        return cls(
            id=data["id"],
            timestamp=data["timestamp"],
            status=MissionStatus(data.get("status", "active")),
            reward=data["reward"],
            availability=data["availability"],
            objectives=objectives
        )


@dataclass
class Stop:
    """
    A stop in a route with pickup and delivery actions.

    Represents visiting a location to pick up and/or deliver cargo.
    """
    location: str
    stop_number: int
    pickups: List[Objective] = field(default_factory=list)
    deliveries: List[Objective] = field(default_factory=list)
    cargo_before: int = 0  # SCU in hold before this stop
    cargo_after: int = 0  # SCU in hold after this stop

    @property
    def total_pickup_scu(self) -> int:
        """Total SCU being picked up at this stop."""
        return sum(obj.scu_amount for obj in self.pickups)

    @property
    def total_delivery_scu(self) -> int:
        """Total SCU being delivered at this stop."""
        return sum(obj.scu_amount for obj in self.deliveries)

    @property
    def net_scu_change(self) -> int:
        """Net change in cargo (pickups - deliveries)."""
        return self.total_pickup_scu - self.total_delivery_scu

    @property
    def has_actions(self) -> bool:
        """Check if this stop has any pickup or delivery actions."""
        return bool(self.pickups or self.deliveries)


@dataclass
class Route:
    """
    An optimized route visiting multiple stops.

    Represents a planned sequence of locations to visit for hauling missions.
    """
    stops: List[Stop]
    starting_location: Optional[str] = None
    total_reward: float = 0.0
    total_scu: int = 0
    mission_count: int = 0

    def __post_init__(self):
        """Calculate route statistics."""
        if not self.stops:
            return

        # Starting location is first stop if not specified
        if not self.starting_location and self.stops:
            self.starting_location = self.stops[0].location

    @property
    def total_stops(self) -> int:
        """Total number of stops in route."""
        return len(self.stops)

    @property
    def max_cargo_load(self) -> int:
        """Maximum cargo load at any point in the route."""
        return max((stop.cargo_after for stop in self.stops), default=0)

    def fits_in_ship(self, ship_capacity: int) -> bool:
        """Check if route fits within ship cargo capacity."""
        return self.max_cargo_load <= ship_capacity

    def get_stop_at_location(self, location: str) -> Optional[Stop]:
        """Get the first stop at a given location."""
        for stop in self.stops:
            if stop.location == location:
                return stop
        return None

    def to_summary(self) -> str:
        """Generate human-readable route summary."""
        lines = [
            f"Route Summary ({self.total_stops} stops)",
            f"Starting Location: {self.starting_location or 'Unknown'}",
            f"Total Reward: {self.total_reward:,.0f} aUEC",
            f"Total SCU: {self.total_scu}",
            f"Max Cargo Load: {self.max_cargo_load} SCU",
            f"Missions: {self.mission_count}",
            "",
            "Stops:"
        ]

        for stop in self.stops:
            lines.append(f"  {stop.stop_number}. {stop.location}")
            if stop.pickups:
                lines.append(f"     ↑ Pick up: {stop.total_pickup_scu} SCU")
            if stop.deliveries:
                lines.append(f"     ↓ Deliver: {stop.total_delivery_scu} SCU")
            lines.append(f"     Cargo: {stop.cargo_before} → {stop.cargo_after} SCU")

        return "\n".join(lines)
