"""
Sync service for uploading/downloading mission scans to/from cloud database.

Communicates with Cloudflare Worker + D1 API.
Requires Discord authentication for all sync operations.
"""

import requests
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from src.logger import get_logger

if TYPE_CHECKING:
    from src.discord_auth import DiscordAuth

logger = get_logger()


class SyncService:
    """Service for syncing mission scans with remote database."""

    def __init__(self, config, discord_auth: Optional["DiscordAuth"] = None):
        self.config = config
        self.discord_auth = discord_auth

    def _get_api_url(self) -> str:
        """Get the sync API URL from config."""
        return self.config.get("sync", "api_url", default="https://your-sync-server.example.com")

    def _get_api_key(self) -> str:
        """Get the sync API key from config (legacy, prefer Discord auth)."""
        return self.config.get("sync", "api_key", default="")

    def _get_auth_headers(self) -> dict:
        """Get authorization headers for API requests."""
        headers = {"Content-Type": "application/json"}

        # Prefer Discord auth token
        if self.discord_auth:
            token = self.discord_auth.get_session_token()
            if token:
                headers["Authorization"] = f"Bearer {token}"
                return headers

        # Fallback to legacy API key
        api_key = self._get_api_key()
        if api_key:
            headers["X-API-Key"] = api_key

        return headers

    def is_authenticated(self) -> bool:
        """Check if user is authenticated (required for sync operations)."""
        if self.discord_auth:
            return self.discord_auth.is_logged_in()
        # Fallback: allow if legacy API key is configured
        return bool(self._get_api_key())

    def get_username(self) -> Optional[str]:
        """Get the username of the authenticated user."""
        if self.discord_auth:
            return self.discord_auth.get_username()
        return self.config.get("sync", "username", default="anonymous")

    def _get_last_sync(self) -> str:
        """Get the last sync timestamp."""
        return self.config.get("sync", "last_sync", default="1970-01-01T00:00:00Z")

    def _set_last_sync(self, timestamp: str):
        """Save the last sync timestamp."""
        if "sync" not in self.config.settings:
            self.config.settings["sync"] = {}
        self.config.settings["sync"]["last_sync"] = timestamp
        self.config.save()

    def is_configured(self) -> bool:
        """Check if sync is properly configured."""
        api_url = self._get_api_url()
        return bool(api_url and api_url.startswith("http"))

    def test_connection(self) -> dict:
        """Test connection to the sync API.

        Returns:
            dict with 'success' and 'message' or 'error'
        """
        api_url = self._get_api_url()
        if not api_url:
            return {"success": False, "error": "Sync API URL not configured"}

        try:
            response = requests.get(
                f"{api_url}/api/health",
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "message": f"Connected successfully at {data.get('timestamp', 'unknown')}"
                }
            else:
                return {
                    "success": False,
                    "error": f"Server returned status {response.status_code}"
                }

        except requests.exceptions.Timeout:
            return {"success": False, "error": "Connection timed out"}
        except requests.exceptions.ConnectionError as e:
            return {"success": False, "error": f"Connection failed: {str(e)}"}
        except Exception as e:
            return {"success": False, "error": f"Error: {str(e)}"}

    def get_stats(self) -> dict:
        """Get statistics from the remote database.

        Returns:
            dict with 'success' and 'stats' or 'error'
        """
        api_url = self._get_api_url()
        if not api_url:
            return {"success": False, "error": "Sync API URL not configured"}

        try:
            response = requests.get(
                f"{api_url}/api/stats",
                timeout=10
            )

            if response.status_code == 200:
                return response.json()
            else:
                return {
                    "success": False,
                    "error": f"Server returned status {response.status_code}"
                }

        except Exception as e:
            return {"success": False, "error": f"Error: {str(e)}"}

    def upload_scans(self, scans: list) -> dict:
        """Upload scans to the remote database.

        Args:
            scans: List of scan dictionaries

        Returns:
            dict with 'success', 'inserted', 'duplicates' or 'error'
        """
        api_url = self._get_api_url()

        if not api_url:
            return {"success": False, "error": "Sync API URL not configured"}

        if not self.is_authenticated():
            return {"success": False, "error": "Authentication required. Please login with Discord."}

        if not scans:
            return {"success": True, "inserted": 0, "duplicates": 0, "message": "No scans to upload"}

        try:
            headers = self._get_auth_headers()

            response = requests.post(
                f"{api_url}/api/scans",
                json={"scans": scans},
                headers=headers,
                timeout=30
            )

            if response.status_code == 200:
                data = response.json()
                logger.info(f"Upload complete: {data.get('inserted', 0)} inserted, {data.get('duplicates', 0)} duplicates")
                return data
            elif response.status_code == 401:
                return {"success": False, "error": "Authentication failed. Please login with Discord."}
            else:
                return {
                    "success": False,
                    "error": f"Server returned status {response.status_code}: {response.text}"
                }

        except requests.exceptions.Timeout:
            return {"success": False, "error": "Upload timed out"}
        except Exception as e:
            logger.error(f"Upload failed: {e}")
            return {"success": False, "error": f"Upload failed: {str(e)}"}

    def download_scans(self, since: Optional[str] = None, location: Optional[str] = None, limit: int = 100) -> dict:
        """Download scans from the remote database.

        Args:
            since: ISO timestamp to get scans after
            location: Filter by scan location
            limit: Maximum number of scans to download

        Returns:
            dict with 'success', 'scans', 'count' or 'error'
        """
        api_url = self._get_api_url()
        if not api_url:
            return {"success": False, "error": "Sync API URL not configured"}

        if not self.is_authenticated():
            return {"success": False, "error": "Authentication required. Please login with Discord."}

        try:
            params = {"limit": limit}
            if since:
                params["since"] = since
            if location:
                params["location"] = location

            headers = self._get_auth_headers()

            response = requests.get(
                f"{api_url}/api/scans",
                params=params,
                headers=headers,
                timeout=30
            )

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 401:
                return {"success": False, "error": "Authentication failed. Please login with Discord."}
            else:
                return {
                    "success": False,
                    "error": f"Server returned status {response.status_code}"
                }

        except requests.exceptions.Timeout:
            return {"success": False, "error": "Download timed out"}
        except Exception as e:
            logger.error(f"Download failed: {e}")
            return {"success": False, "error": f"Download failed: {str(e)}"}

    def sync(self, local_scans: list) -> dict:
        """Perform two-way sync.

        Uploads local scans and downloads new scans from others.

        Args:
            local_scans: List of local scan dictionaries

        Returns:
            dict with 'success', 'uploaded', 'downloaded', 'sync_timestamp' or 'error'
        """
        api_url = self._get_api_url()
        last_sync = self._get_last_sync()

        if not api_url:
            return {"success": False, "error": "Sync API URL not configured"}

        if not self.is_authenticated():
            return {"success": False, "error": "Authentication required. Please login with Discord."}

        try:
            headers = self._get_auth_headers()

            response = requests.post(
                f"{api_url}/api/sync",
                json={
                    "scans": local_scans,
                    "last_sync": last_sync,
                },
                headers=headers,
                timeout=60
            )

            if response.status_code == 200:
                data = response.json()

                # Update last sync timestamp
                if data.get("success") and data.get("sync_timestamp"):
                    self._set_last_sync(data["sync_timestamp"])

                logger.info(
                    f"Sync complete: uploaded {data.get('uploaded', 0)}, "
                    f"downloaded {len(data.get('downloaded', []))}"
                )
                return data

            elif response.status_code == 401:
                return {"success": False, "error": "Authentication failed. Please login with Discord."}
            else:
                return {
                    "success": False,
                    "error": f"Server returned status {response.status_code}: {response.text}"
                }

        except requests.exceptions.Timeout:
            return {"success": False, "error": "Sync timed out"}
        except Exception as e:
            logger.error(f"Sync failed: {e}")
            return {"success": False, "error": f"Sync failed: {str(e)}"}
