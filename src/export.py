"""
Export functionality for missions.

Supports exporting to CSV and JSON formats.
"""

import csv
import json
from datetime import datetime
from typing import List, Dict, Any
from pathlib import Path

from src.logger import get_logger

logger = get_logger()


class MissionExporter:
    """Handles exporting missions to various formats."""

    @staticmethod
    def export_to_csv(missions: List[Dict[str, Any]], output_path: str) -> bool:
        """
        Export missions to CSV format.

        Creates a flat structure suitable for spreadsheets.
        Each row represents one objective.

        Args:
            missions: List of mission dictionaries
            output_path: Path to output CSV file

        Returns:
            True if export succeeded
        """
        try:
            with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = [
                    'mission_id',
                    'mission_timestamp',
                    'status',
                    'reward',
                    'availability',
                    'objective_number',
                    'collect_from',
                    'deliver_to',
                    'scu_amount'
                ]

                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()

                for mission in missions:
                    mission_id = mission.get('id', 'unknown')
                    timestamp = mission.get('timestamp', '')
                    status = mission.get('status', 'active')
                    reward = mission.get('reward', 0)
                    availability = mission.get('availability', '')

                    objectives = mission.get('objectives', [])

                    for i, obj in enumerate(objectives, 1):
                        writer.writerow({
                            'mission_id': mission_id[:8],  # Shortened ID
                            'mission_timestamp': timestamp,
                            'status': status,
                            'reward': reward,
                            'availability': availability,
                            'objective_number': i,
                            'collect_from': obj.get('collect_from', ''),
                            'deliver_to': obj.get('deliver_to', ''),
                            'scu_amount': obj.get('scu_amount', 0)
                        })

            logger.info(f"Exported {len(missions)} missions to CSV: {output_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to export to CSV: {e}")
            return False

    @staticmethod
    def export_to_json(missions: List[Dict[str, Any]], output_path: str, pretty: bool = True) -> bool:
        """
        Export missions to JSON format.

        Args:
            missions: List of mission dictionaries
            output_path: Path to output JSON file
            pretty: If True, format with indentation

        Returns:
            True if export succeeded
        """
        try:
            with open(output_path, 'w', encoding='utf-8') as jsonfile:
                if pretty:
                    json.dump(missions, jsonfile, indent=2, ensure_ascii=False)
                else:
                    json.dump(missions, jsonfile, ensure_ascii=False)

            logger.info(f"Exported {len(missions)} missions to JSON: {output_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to export to JSON: {e}")
            return False

    @staticmethod
    def export_summary_to_txt(missions: List[Dict[str, Any]], output_path: str) -> bool:
        """
        Export mission summary to text file.

        Creates a human-readable summary report.

        Args:
            missions: List of mission dictionaries
            output_path: Path to output text file

        Returns:
            True if export succeeded
        """
        try:
            with open(output_path, 'w', encoding='utf-8') as txtfile:
                txtfile.write("=" * 80 + "\n")
                txtfile.write("SC HAULING ASSISTANT - MISSION EXPORT\n")
                txtfile.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                txtfile.write("=" * 80 + "\n\n")

                # Summary statistics
                total_missions = len(missions)
                active_missions = sum(1 for m in missions if m.get('status') == 'active')
                total_reward = sum(m.get('reward', 0) for m in missions)
                total_scu = sum(
                    sum(obj.get('scu_amount', 0) for obj in m.get('objectives', []))
                    for m in missions
                )

                txtfile.write(f"Total Missions: {total_missions}\n")
                txtfile.write(f"Active Missions: {active_missions}\n")
                txtfile.write(f"Total Reward: {total_reward:,.0f} aUEC\n")
                txtfile.write(f"Total SCU: {total_scu}\n")
                txtfile.write("\n" + "=" * 80 + "\n\n")

                # Mission details
                for i, mission in enumerate(missions, 1):
                    mission_id = mission.get('id', 'unknown')[:8]
                    status = mission.get('status', 'active')
                    reward = mission.get('reward', 0)
                    availability = mission.get('availability', '')
                    objectives = mission.get('objectives', [])

                    txtfile.write(f"MISSION {i} ({mission_id}) - {status.upper()}\n")
                    txtfile.write(f"Reward: {reward:,.0f} aUEC | Time Left: {availability}\n")
                    txtfile.write(f"Objectives:\n")

                    for j, obj in enumerate(objectives, 1):
                        collect_from = obj.get('collect_from', '?')
                        deliver_to = obj.get('deliver_to', '?')
                        scu = obj.get('scu_amount', 0)
                        txtfile.write(f"  {j}. {scu} SCU: {collect_from} → {deliver_to}\n")

                    txtfile.write("\n")

            logger.info(f"Exported mission summary to text: {output_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to export summary to text: {e}")
            return False

    @staticmethod
    def get_default_export_filename(format: str, status_filter: str = None) -> str:
        """
        Generate a default export filename with timestamp.

        Args:
            format: Export format ('csv', 'json', 'txt')
            status_filter: Optional status filter for filename

        Returns:
            Filename string
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        status_part = f"_{status_filter}" if status_filter else ""
        return f"missions_export{status_part}_{timestamp}.{format}"

    @staticmethod
    def ensure_export_directory() -> Path:
        """
        Ensure export directory exists.

        Returns:
            Path to export directory
        """
        export_dir = Path("exports")
        export_dir.mkdir(exist_ok=True)
        return export_dir
