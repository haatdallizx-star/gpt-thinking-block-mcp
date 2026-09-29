# Hardened Succhia Bridge Spec

## Goal

Connect a FUNF 啵啵贝 Pro (`SOSEXY`) through an Android Chrome Web Bluetooth bridge to the existing HTTPS/MCP service on the VPS, while keeping first-use controls deliberately conservative.

## Architecture

- Extend the already deployed `gpt-thinking` Python service and reuse its HTTPS reverse-proxy path.
- Serve the Android control page at `/succhia` and the bridge API below `/succhia-api`.
- Expose Succhia MCP tools only when the MCP request includes a separate long random token.
- Store device state locally in the service and let the Android page long-poll for updates.

## Safety and access constraints

- EMS is disabled end to end: no control in the page, no MCP field, and server state always forces it to zero.
- Suction and vibration are capped at 30/100 for the first deployment.
- Every non-zero remote command has a lease of 3-120 seconds; expiry sets both enabled channels and all patterns to zero.
- A BLE disconnect immediately clears local pending commands and zeroes server state; reconnect never restores the previous non-zero state.
- Manual Stop remains available without navigating away from the control page.
- The page API and MCP access use different generated secrets.
- The page API secret is sent as `X-Succhia-Token`; the MCP secret is supplied in the connector URL query string and is never returned by status/diagnostic endpoints.
- Existing thinking-block behavior remains unchanged for callers without the Succhia MCP token.

## Initial acceptance check

1. Android Chrome opens the HTTPS control page and authenticates.
2. The page discovers and connects to Bluetooth device name `SOSEXY`.
3. A manual 5/100 vibration command runs for one second and returns to zero.
4. Disconnecting and reconnecting leaves every channel at zero.
5. An authenticated MCP status call reports the page online; an unauthenticated MCP tools list does not expose Succhia tools.

