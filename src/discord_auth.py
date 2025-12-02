"""
Discord OAuth2 authentication for SC Hauling Assistant.

Handles the OAuth flow, credential storage, and session management.
"""

import http.server
import json
import secrets
import socketserver
import threading
import urllib.parse
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Callable

import requests

try:
    import keyring
    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False

from src.config import Config
from src.logger import get_logger

logger = get_logger()

# Discord OAuth2 configuration
DISCORD_CLIENT_ID = "1445206968250794014"
DISCORD_AUTH_URL = "https://discord.com/api/oauth2/authorize"
CALLBACK_PORT = 47832
CALLBACK_TIMEOUT = 120  # seconds

# Credential storage keys
CREDENTIAL_SERVICE = "SC-Hauling-Assistant"
CREDENTIAL_SESSION = "discord_session"
CREDENTIAL_USER = "discord_user"


@dataclass
class DiscordUser:
    """Represents an authenticated Discord user."""
    discord_id: str
    username: str
    avatar: Optional[str] = None


@dataclass
class AuthCredentials:
    """Stored authentication credentials."""
    session_token: str
    username: str
    discord_id: str
    expires_at: str


class OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler for OAuth callback."""

    auth_code: Optional[str] = None
    auth_state: Optional[str] = None
    error: Optional[str] = None

    def log_message(self, format, *args):
        """Suppress HTTP server logs."""
        pass

    def do_GET(self):
        """Handle GET request from Discord redirect."""
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == '/callback':
            params = urllib.parse.parse_qs(parsed.query)

            if 'error' in params:
                OAuthCallbackHandler.error = params.get('error', ['unknown'])[0]
                self._send_response("Authentication failed. You can close this window.")
            elif 'code' in params:
                OAuthCallbackHandler.auth_code = params.get('code', [None])[0]
                OAuthCallbackHandler.auth_state = params.get('state', [None])[0]
                self._send_response("Authentication successful! You can close this window.")
            else:
                self._send_response("Invalid callback. You can close this window.")
        else:
            self.send_error(404)

    def _send_response(self, message: str):
        """Send HTML response to browser."""
        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>SC Hauling Assistant - Discord Login</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #eee;
        }}
        .container {{
            text-align: center;
            padding: 40px;
            background: rgba(255,255,255,0.1);
            border-radius: 12px;
            backdrop-filter: blur(10px);
        }}
        h1 {{ margin-bottom: 16px; }}
        p {{ color: #aaa; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>{message}</h1>
        <p>Return to SC Hauling Assistant</p>
    </div>
</body>
</html>"""
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(html.encode())


class DiscordAuth:
    """Manages Discord OAuth authentication."""

    def __init__(self, config: Config):
        self.config = config
        self._callback_server = None
        self._server_thread = None
        self._expected_state: Optional[str] = None

    def get_api_url(self) -> str:
        """Get the sync API base URL."""
        return self.config.get("sync", "api_url", default="")

    def is_logged_in(self) -> bool:
        """Check if user has valid stored credentials."""
        creds = self._get_stored_credentials()
        if not creds:
            return False

        # Check if token is expired
        try:
            expires = datetime.fromisoformat(creds.expires_at.replace('Z', '+00:00'))
            if expires < datetime.now(expires.tzinfo):
                logger.debug("Session token expired")
                self._clear_credentials()
                return False
        except (ValueError, AttributeError):
            return False

        return True

    def get_session_token(self) -> Optional[str]:
        """Get stored session token if valid."""
        if not self.is_logged_in():
            return None
        creds = self._get_stored_credentials()
        return creds.session_token if creds else None

    def get_username(self) -> Optional[str]:
        """Get Discord username of logged-in user."""
        creds = self._get_stored_credentials()
        return creds.username if creds else None

    def get_user(self) -> Optional[DiscordUser]:
        """Get full user info if logged in."""
        creds = self._get_stored_credentials()
        if not creds:
            return None
        return DiscordUser(
            discord_id=creds.discord_id,
            username=creds.username
        )

    def start_login_flow(self, on_complete: Optional[Callable[[bool, str], None]] = None) -> dict:
        """
        Start OAuth flow. Opens browser for Discord authorization.

        Args:
            on_complete: Optional callback(success: bool, message: str)

        Returns:
            dict with 'success' and 'message' or 'error'
        """
        try:
            # Generate state for CSRF protection
            self._expected_state = secrets.token_urlsafe(32)

            # Reset callback handler state
            OAuthCallbackHandler.auth_code = None
            OAuthCallbackHandler.auth_state = None
            OAuthCallbackHandler.error = None

            # Build authorization URL
            redirect_uri = f"http://127.0.0.1:{CALLBACK_PORT}/callback"
            auth_params = {
                'client_id': DISCORD_CLIENT_ID,
                'redirect_uri': redirect_uri,
                'response_type': 'code',
                'scope': 'identify',
                'state': self._expected_state,
            }
            auth_url = f"{DISCORD_AUTH_URL}?{urllib.parse.urlencode(auth_params)}"

            # Start callback server
            self._start_callback_server()

            # Open browser
            logger.info("Opening Discord authorization in browser")
            webbrowser.open(auth_url)

            # Wait for callback (blocking)
            result = self._wait_for_callback(redirect_uri)

            if on_complete:
                on_complete(result.get('success', False), result.get('message', result.get('error', '')))

            return result

        except Exception as e:
            logger.error(f"Login flow error: {e}")
            error_result = {'success': False, 'error': str(e)}
            if on_complete:
                on_complete(False, str(e))
            return error_result
        finally:
            self._stop_callback_server()

    def logout(self) -> None:
        """Clear stored credentials and invalidate session on server."""
        token = self.get_session_token()

        if token:
            # Try to invalidate on server (best effort)
            try:
                api_url = self.get_api_url()
                response = requests.post(
                    f"{api_url}/api/auth/logout",
                    headers={'Authorization': f'Bearer {token}'},
                    timeout=10
                )
                if response.ok:
                    logger.info("Session invalidated on server")
            except Exception as e:
                logger.warning(f"Could not invalidate session on server: {e}")

        self._clear_credentials()
        logger.info("Logged out successfully")

    def verify_session(self) -> bool:
        """Verify current session is still valid with server."""
        token = self.get_session_token()
        if not token:
            return False

        try:
            api_url = self.get_api_url()
            response = requests.get(
                f"{api_url}/api/auth/me",
                headers={'Authorization': f'Bearer {token}'},
                timeout=10
            )
            if response.ok:
                data = response.json()
                if data.get('success'):
                    # Update stored username in case it changed
                    user = data.get('user', {})
                    creds = self._get_stored_credentials()
                    if creds and user.get('username') != creds.username:
                        self._store_credentials(
                            creds.session_token,
                            user.get('username', creds.username),
                            user.get('discord_id', creds.discord_id),
                            creds.expires_at
                        )
                    return True
            else:
                # Token invalid, clear credentials
                self._clear_credentials()
                return False
        except Exception as e:
            logger.warning(f"Could not verify session: {e}")
            # Don't clear credentials on network error, let local check handle it
            return self.is_logged_in()

    def _start_callback_server(self):
        """Start temporary HTTP server for OAuth callback."""
        try:
            # Allow socket reuse to avoid "address already in use" errors
            socketserver.TCPServer.allow_reuse_address = True
            self._callback_server = socketserver.TCPServer(
                ('127.0.0.1', CALLBACK_PORT),
                OAuthCallbackHandler
            )
            self._callback_server.timeout = CALLBACK_TIMEOUT
            logger.debug(f"Callback server started on port {CALLBACK_PORT}")
        except OSError as e:
            raise Exception(f"Could not start callback server: {e}")

    def _stop_callback_server(self):
        """Stop the callback server."""
        if self._callback_server:
            try:
                # Close the socket directly for immediate release
                self._callback_server.socket.close()
            except Exception as e:
                logger.debug(f"Error closing callback server socket: {e}")
            try:
                self._callback_server.server_close()
            except Exception as e:
                logger.debug(f"Error closing callback server: {e}")
            self._callback_server = None
            logger.debug("Callback server stopped")

    def _wait_for_callback(self, redirect_uri: str) -> dict:
        """Wait for OAuth callback and exchange code for token."""
        if not self._callback_server:
            return {'success': False, 'error': 'Callback server not running'}

        # Handle one request (blocking)
        self._callback_server.handle_request()

        # Check for errors
        if OAuthCallbackHandler.error:
            return {'success': False, 'error': f'Discord error: {OAuthCallbackHandler.error}'}

        if not OAuthCallbackHandler.auth_code:
            return {'success': False, 'error': 'No authorization code received'}

        # Verify state parameter
        if OAuthCallbackHandler.auth_state != self._expected_state:
            return {'success': False, 'error': 'Invalid state parameter (possible CSRF attack)'}

        # Exchange code for session token via our API
        return self._exchange_code(OAuthCallbackHandler.auth_code, redirect_uri)

    def _exchange_code(self, code: str, redirect_uri: str) -> dict:
        """Exchange authorization code for session token via Cloudflare Worker."""
        try:
            api_url = self.get_api_url()
            response = requests.post(
                f"{api_url}/api/auth/discord/callback",
                json={
                    'code': code,
                    'redirect_uri': redirect_uri,
                },
                timeout=30
            )

            if not response.ok:
                error_data = response.json() if response.headers.get('content-type', '').startswith('application/json') else {}
                return {'success': False, 'error': error_data.get('error', f'Server error: {response.status_code}')}

            data = response.json()

            if not data.get('success'):
                return {'success': False, 'error': data.get('error', 'Unknown error')}

            # Store credentials
            user = data.get('user', {})
            self._store_credentials(
                data['session_token'],
                user.get('username', 'Unknown'),
                user.get('discord_id', ''),
                data.get('expires_at', '')
            )

            logger.info(f"Logged in as {user.get('username')}")
            return {
                'success': True,
                'message': f"Logged in as {user.get('username')}",
                'user': user
            }

        except requests.exceptions.Timeout:
            return {'success': False, 'error': 'Server request timed out'}
        except requests.exceptions.ConnectionError:
            return {'success': False, 'error': 'Could not connect to server'}
        except Exception as e:
            logger.error(f"Code exchange error: {e}")
            return {'success': False, 'error': str(e)}

    def _store_credentials(self, token: str, username: str, discord_id: str, expires_at: str) -> None:
        """Store credentials securely."""
        creds_data = json.dumps({
            'session_token': token,
            'username': username,
            'discord_id': discord_id,
            'expires_at': expires_at,
        })

        if KEYRING_AVAILABLE:
            try:
                keyring.set_password(CREDENTIAL_SERVICE, CREDENTIAL_SESSION, creds_data)
                logger.debug("Credentials stored in system keyring")
                return
            except Exception as e:
                logger.warning(f"Keyring storage failed: {e}, falling back to config")

        # Fallback to config file (less secure but functional)
        self.config.set("sync", "discord_credentials", creds_data)
        self.config.save()
        logger.debug("Credentials stored in config file")

    def _get_stored_credentials(self) -> Optional[AuthCredentials]:
        """Retrieve stored credentials."""
        creds_data = None

        if KEYRING_AVAILABLE:
            try:
                creds_data = keyring.get_password(CREDENTIAL_SERVICE, CREDENTIAL_SESSION)
            except Exception as e:
                logger.debug(f"Keyring read failed: {e}")

        if not creds_data:
            # Try config fallback
            creds_data = self.config.get("sync", "discord_credentials")

        if not creds_data:
            return None

        try:
            data = json.loads(creds_data)
            return AuthCredentials(
                session_token=data['session_token'],
                username=data['username'],
                discord_id=data['discord_id'],
                expires_at=data['expires_at'],
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Invalid stored credentials: {e}")
            return None

    def _clear_credentials(self) -> None:
        """Clear stored credentials."""
        if KEYRING_AVAILABLE:
            try:
                keyring.delete_password(CREDENTIAL_SERVICE, CREDENTIAL_SESSION)
            except Exception:
                pass

        # Also clear from config if present
        try:
            if self.config.get("sync", "discord_credentials"):
                self.config.set("sync", "discord_credentials", value=None)
                self.config.save()
        except Exception:
            pass

        logger.debug("Credentials cleared")
