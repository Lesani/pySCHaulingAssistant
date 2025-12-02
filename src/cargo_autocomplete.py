"""
Cargo type autocomplete with fuzzy matching.

Loads Star Citizen commodity data and provides filtered suggestions.
"""

import json
import os
from typing import List


class CargoMatcher:
    """Provides fuzzy matching for Star Citizen cargo types."""

    def __init__(self, data_dir: str = "src/cargo_data") -> None:
        self.data_dir = data_dir
        self.all_cargo_types: List[str] = []
        self.load_cargo_types()

    def load_cargo_types(self) -> None:
        """Load all cargo type names from JSON file."""
        self.all_cargo_types = []

        # Load commodities
        commodities_path = os.path.join(self.data_dir, "commodities.json")
        if os.path.exists(commodities_path):
            self._extract_cargo_types_from_file(commodities_path)

        # Remove duplicates and sort
        self.all_cargo_types = sorted(set(self.all_cargo_types))

    def _extract_cargo_types_from_file(self, filepath: str) -> None:
        """Extract all cargo type names from a JSON file."""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Extract from categories
            if "categories" in data:
                for category, cargo_list in data["categories"].items():
                    if isinstance(cargo_list, list):
                        self.all_cargo_types.extend(cargo_list)

        except (json.JSONDecodeError, IOError) as e:
            print(f"Error loading cargo data from {filepath}: {e}")

    def fuzzy_match(self, query: str, limit: int = 10) -> List[str]:
        """
        Find cargo types matching the query using fuzzy matching.

        Args:
            query: Search string
            limit: Maximum number of results

        Returns:
            List of matching cargo type names, sorted by relevance
        """
        if not query:
            return self.all_cargo_types[:limit]

        query_lower = query.lower()
        matches = []

        for cargo_type in self.all_cargo_types:
            cargo_type_lower = cargo_type.lower()

            # Exact match (highest priority)
            if cargo_type_lower == query_lower:
                matches.append((cargo_type, 0))
            # Starts with query (high priority)
            elif cargo_type_lower.startswith(query_lower):
                matches.append((cargo_type, 1))
            # Contains query (medium priority)
            elif query_lower in cargo_type_lower:
                matches.append((cargo_type, 2))
            # Word-level fuzzy match (lower priority)
            elif self._word_match(query_lower, cargo_type_lower):
                matches.append((cargo_type, 3))

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

    def get_all_cargo_types(self) -> List[str]:
        """Get complete list of all cargo types."""
        return self.all_cargo_types.copy()

    def get_cargo_types_by_prefix(self, prefix: str, limit: int = 10) -> List[str]:
        """
        Get cargo types starting with prefix (case-insensitive).

        Args:
            prefix: Prefix to match
            limit: Maximum number of results

        Returns:
            List of matching cargo type names
        """
        if not prefix:
            return self.all_cargo_types[:limit]

        prefix_lower = prefix.lower()
        matches = [
            cargo_type for cargo_type in self.all_cargo_types
            if cargo_type.lower().startswith(prefix_lower)
        ]
        return matches[:limit]
