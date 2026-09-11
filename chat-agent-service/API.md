# MCP Per-User OAuth2 API & Frontend Guide

This document describes the Per-User OAuth2 integration for MCP servers (e.g. Google Calendar, Gmail, Drive) within `chat-agent-service`.

---

## 1. Overview

By default, an `McpServer` with `auth_config: {"type": "bearer", "token": "..."}` uses a single credential shared by all users.

For personal integrations, an `McpServer` is configured with:
```json
{
  "type": "oauth2_per_user",
  "scopes": [
    "https://www.googleapis.com/auth/calendar"
  ]
}
```

Each user connects their own account. The service encrypts and stores tokens securely at rest using Fernet symmetric encryption (`TOKEN_ENCRYPTION_KEY`).

If a user has not connected yet:
- The agent **gracefully omits** those tools from the model call.
- A system prompt note is injected instructing the assistant to inform the user to connect their account.
- The chat turn will **never fail or error out** due to missing OAuth credentials.

---

## 2. API Endpoints

All endpoints except the OAuth callback require user authentication (`Authorization: Bearer <jwt>`).

### `GET /api/v1/mcp-servers/{id}/oauth/authorize`
- **Auth required**: Yes
- **Description**: Generates a signed Google OAuth consent URL with CSRF protection (`state`).
- **Response**:
  ```json
  {
    "authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?client_id=...&state=..."
  }
  ```
- **Error Codes**:
  - `404 Not Found`: Server does not exist or its `auth_config.type != "oauth2_per_user"`.

### `GET /api/v1/mcp-servers/{id}/oauth/callback`
- **Auth required**: No (Public redirect endpoint called by Google)
- **Query Parameters**:
  - `code`: Authorization code from Google
  - `state`: Signed JWT state containing `{mcp_server_id, user_id, exp, iat}`
- **Behavior**:
  - Verifies state signature, integrity, and expiration.
  - Exchanges `code` with Google's token endpoint (`https://oauth2.googleapis.com/token`).
  - Stores encrypted `access_token` and `refresh_token` in `mcp_user_connections`.
  - Redirects to `OAUTH_SUCCESS_REDIRECT_URL` if configured in settings; otherwise returns a lightweight HTML success message.

### `GET /api/v1/mcp-servers/{id}/my-connection`
- **Auth required**: Yes
- **Description**: Checks whether the authenticated user has an active OAuth connection for this MCP server. Never exposes tokens.
- **Response**:
  ```json
  {
    "connected": true,
    "status": "connected",
    "expires_at": "2026-09-11T18:30:00+00:00",
    "scopes": "https://www.googleapis.com/auth/calendar",
    "last_error": null
  }
  ```

### `DELETE /api/v1/mcp-servers/{id}/my-connection`
- **Auth required**: Yes
- **Status**: `204 No Content`
- **Description**: Disconnects the user's connection by deleting their `McpUserConnection` record.
- **Error Codes**:
  - `404 Not Found`: If no connection existed for this user.

---

## 3. Frontend Integration Flow

### Connecting an Account
1. User clicks "Connect Google Account" / "Connect Calendar" in the UI.
2. Frontend calls `GET /api/v1/mcp-servers/{id}/oauth/authorize`.
3. Frontend opens the returned `authorization_url` in a popup window or new tab.
4. User grants consent in Google's OAuth screen.
5. Google redirects the popup to `GET /api/v1/mcp-servers/{id}/oauth/callback`.
6. Frontend polls or listens for the popup window closing.
7. Upon popup closure, frontend re-fetches `GET /api/v1/mcp-servers/{id}/my-connection` to confirm `connected: true` and updates the UI state.

### Disconnecting
1. User clicks "Disconnect".
2. Frontend sends `DELETE /api/v1/mcp-servers/{id}/my-connection`.
3. Frontend updates UI state to show disconnected.

### Chat & Tool Availability UX
- Agents configured with `oauth2_per_user` MCP servers will silently skip tools for users who haven't connected yet.
- The frontend should proactively display connection status and a "Connect" button in the agent view or toolbar, rather than relying solely on the assistant's message.

---

## 4. Known Gaps & Limitations (v1)

- **Provider Scope**: Only Google OAuth2 is supported in v1 (expandable to other OAuth2 providers via the same pattern).
- **Token Revocation on Disconnect**: `DELETE /mcp-servers/{id}/my-connection` performs a hard database delete of stored tokens. Revocation via Google's `https://oauth2.googleapis.com/revoke` endpoint is not implemented in v1.
