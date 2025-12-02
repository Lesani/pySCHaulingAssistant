"""
JSON schema validation for mission data.

Ensures data integrity and prevents corruption.
"""

from typing import Dict, Any, List, Tuple
import jsonschema
from jsonschema import validate, ValidationError

from src.logger import get_logger

logger = get_logger()


# JSON Schema for a single mission
MISSION_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["id", "timestamp", "reward", "availability", "objectives"],
    "properties": {
        "id": {
            "type": "string",
            "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            "description": "UUID v4 format"
        },
        "timestamp": {
            "type": "string",
            "format": "date-time",
            "description": "ISO 8601 timestamp"
        },
        "status": {
            "type": "string",
            "enum": ["active", "completed", "expired"],
            "description": "Mission status"
        },
        "rank": {
            "type": "string",
            "description": "Mission rank (Trainee, Rookie, Junior, Member, Experienced, Senior, Master)"
        },
        "contracted_by": {
            "type": "string",
            "description": "Organization that contracted the mission (e.g., Covalex Shipping)"
        },
        "reward": {
            "type": "number",
            "minimum": 0,
            "description": "Mission reward in aUEC"
        },
        "availability": {
            "type": "string",
            "description": "Time remaining (HH:MM:SS or N/A)"
        },
        "objectives": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["collect_from", "scu_amount", "deliver_to"],
                "properties": {
                    "collect_from": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Source location name"
                    },
                    "cargo_type": {
                        "type": "string",
                        "description": "Type of cargo to haul (optional)"
                    },
                    "scu_amount": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Cargo amount in SCU"
                    },
                    "deliver_to": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Destination location name"
                    },
                    "mission_id": {
                        "type": "string",
                        "description": "Parent mission ID (added automatically)"
                    }
                },
                "additionalProperties": False
            }
        }
    },
    "additionalProperties": False
}

# Schema for missions.json file (array of missions with version)
MISSIONS_FILE_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["version", "missions"],
    "properties": {
        "version": {
            "type": "string",
            "pattern": "^\\d+\\.\\d+$",
            "description": "Data format version (e.g., '2.0')"
        },
        "missions": {
            "type": "array",
            "items": MISSION_SCHEMA
        }
    },
    "additionalProperties": False
}


def validate_mission(mission_data: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Validate a single mission against the schema.

    Args:
        mission_data: Mission dictionary to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        validate(instance=mission_data, schema=MISSION_SCHEMA)
        return True, ""
    except ValidationError as e:
        error_msg = f"Validation error: {e.message} at {'.'.join(str(p) for p in e.path)}"
        logger.warning(f"Mission validation failed: {error_msg}")
        return False, error_msg
    except Exception as e:
        error_msg = f"Unexpected validation error: {e}"
        logger.error(error_msg)
        return False, error_msg


def validate_missions_file(file_data: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Validate missions.json file structure.

    Args:
        file_data: Entire file contents as dictionary

    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        validate(instance=file_data, schema=MISSIONS_FILE_SCHEMA)
        return True, ""
    except ValidationError as e:
        error_msg = f"File validation error: {e.message}"
        logger.warning(f"Missions file validation failed: {error_msg}")
        return False, error_msg
    except Exception as e:
        error_msg = f"Unexpected file validation error: {e}"
        logger.error(error_msg)
        return False, error_msg


def validate_mission_list(missions: List[Dict[str, Any]]) -> Tuple[bool, List[str]]:
    """
    Validate a list of missions.

    Args:
        missions: List of mission dictionaries

    Returns:
        Tuple of (all_valid, list_of_errors)
    """
    errors = []

    for i, mission in enumerate(missions):
        is_valid, error_msg = validate_mission(mission)
        if not is_valid:
            errors.append(f"Mission {i} ({mission.get('id', 'unknown')}): {error_msg}")

    return len(errors) == 0, errors


def sanitize_mission(mission_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sanitize and fix common mission data issues.

    Args:
        mission_data: Mission dictionary to sanitize

    Returns:
        Sanitized mission dictionary
    """
    sanitized = mission_data.copy()

    # Ensure status exists
    if "status" not in sanitized:
        sanitized["status"] = "active"
        logger.debug(f"Added missing status to mission {sanitized.get('id')}")

    # Ensure reward is a number
    if isinstance(sanitized.get("reward"), str):
        try:
            sanitized["reward"] = float(sanitized["reward"])
            logger.debug(f"Converted reward to float for mission {sanitized.get('id')}")
        except ValueError:
            logger.warning(f"Could not convert reward '{sanitized['reward']}' to float")

    # Sanitize objectives
    allowed_obj_fields = {"collect_from", "cargo_type", "scu_amount", "deliver_to", "mission_id"}
    sanitized_objectives = []

    for obj in sanitized.get("objectives", []):
        # Ensure scu_amount is an integer
        if isinstance(obj.get("scu_amount"), str):
            try:
                obj["scu_amount"] = int(obj["scu_amount"])
            except ValueError:
                logger.warning(f"Could not convert scu_amount '{obj['scu_amount']}' to int")

        # Filter out any unexpected fields
        sanitized_obj = {k: v for k, v in obj.items() if k in allowed_obj_fields}

        # Add default cargo_type if missing
        if "cargo_type" not in sanitized_obj:
            sanitized_obj["cargo_type"] = "Unknown"

        sanitized_objectives.append(sanitized_obj)

    sanitized["objectives"] = sanitized_objectives

    return sanitized


def get_data_version() -> str:
    """Get current data format version."""
    return "2.0"


def create_versioned_file_structure(missions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Create versioned file structure for missions.json.

    Args:
        missions: List of mission dictionaries

    Returns:
        Versioned file structure
    """
    return {
        "version": get_data_version(),
        "missions": missions
    }


def is_legacy_format(file_data: Any) -> bool:
    """
    Check if file is in legacy format (array of missions without version).

    Args:
        file_data: Loaded JSON data

    Returns:
        True if legacy format
    """
    return isinstance(file_data, list)


def migrate_from_legacy(legacy_missions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Migrate from legacy format (array) to versioned format.

    Args:
        legacy_missions: List of mission dictionaries (old format)

    Returns:
        Versioned file structure (new format)
    """
    logger.info(f"Migrating {len(legacy_missions)} missions from legacy format to v2.0")

    # Sanitize all missions
    sanitized_missions = [sanitize_mission(m) for m in legacy_missions]

    return create_versioned_file_structure(sanitized_missions)
