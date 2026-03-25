"""
Claude OAuth authentication.
Uses the same OAuth mechanism as Claude Code:
- Opens browser to https://claude.ai/oauth/authorize
- Receives token via local redirect
- Stores token in Keyring
"""
import webbrowser
import threading
import httpx
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, urlencode
import logging
from typing import Optional

from claudeclaw.auth.keyring import CredentialStore

logger = logging.getLogger(__name__)

TOKEN_KEY = "claude-oauth-token"
OAUTH_URL = "https://claude.ai/oauth/authorize"
REDIRECT_PORT = 54321
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/callback"
# IMPORTANT: The exact OAuth client_id, scopes, and token exchange endpoint must be
# obtained from Anthropic's official documentation or by inspecting how Claude Code
# performs its own `claude auth login` flow (check the claude binary's network traffic).
# The values below are stubs. The login() method implements the authorization code flow
# correctly (code → token exchange), but _exchange_code() is a stub that must be filled
# in with the real Anthropic token endpoint before this command will work.
CLIENT_ID = "claudeclaw"   # STUB — replace with real Anthropic OAuth client_id
SCOPE = "claude:messages"  # STUB — replace with real required scopes


class AuthError(Exception):
    pass


class _CallbackHandler(BaseHTTPRequestHandler):
    def __init__(self, *args, token_container: list, **kwargs):
        self._token_container = token_container
        super().__init__(*args, **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        token = params.get("token", [None])[0] or params.get("code", [None])[0]
        self._token_container[0] = token
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"<html><body><h2>ClaudeClaw authenticated. You can close this tab.</h2></body></html>")

    def log_message(self, *args):
        pass  # suppress request logs


class AuthManager:
    def __init__(self, store: Optional[CredentialStore] = None):
        self._store = store or CredentialStore()

    def is_logged_in(self) -> bool:
        return self._store.get(TOKEN_KEY) is not None

    def get_token(self) -> str:
        token = self._store.get(TOKEN_KEY)
        if not token:
            raise AuthError("not logged in. Run: claudeclaw login")
        return token

    def login(self) -> None:
        """Open browser for OAuth and wait for redirect with authorization code, then exchange for token."""
        token_container = [None]

        def handler_factory(*args, **kwargs):
            return _CallbackHandler(*args, token_container=token_container, **kwargs)

        server = HTTPServer(("localhost", REDIRECT_PORT), handler_factory)
        server.socket.settimeout(120)
        thread = threading.Thread(target=server.handle_request)
        thread.start()

        params = urlencode({
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPE,
            "response_type": "code",
        })
        auth_url = f"{OAUTH_URL}?{params}"
        logger.info("Opening browser for Claude authentication...")
        webbrowser.open(auth_url)
        thread.join(timeout=120)
        server.server_close()

        code = token_container[0]
        if not code:
            raise AuthError("Authentication timed out or was cancelled.")

        # Exchange authorization code for access token
        token = self._exchange_code(code)
        self._store.set(TOKEN_KEY, token)
        logger.info("Logged in successfully.")

    def _exchange_code(self, code: str) -> str:
        """
        Exchange OAuth authorization code for an access token.
        STUB: Fill in the real Anthropic token endpoint and parameters.
        Until this is implemented, store the code directly for local testing only.
        """
        # TODO: Replace with real Anthropic token endpoint discovered from Claude Code OAuth flow
        # response = httpx.post("https://claude.ai/oauth/token", data={
        #     "grant_type": "authorization_code",
        #     "code": code,
        #     "redirect_uri": REDIRECT_URI,
        #     "client_id": CLIENT_ID,
        # })
        # response.raise_for_status()
        # return response.json()["access_token"]
        logger.warning("OAuth token exchange not implemented — storing code as token (dev only)")
        return code

    def logout(self) -> None:
        self._store.delete(TOKEN_KEY)
        logger.info("Logged out.")
