# ControlPLANE live playground patch

This patch replaces the public showcase's prerecorded GatewayDemo with a prompt playground that sends real requests to the existing gateway, and adds a same-origin Next.js route to proxy the request server-side.

## Files

- `showcase/components/sections/GatewayDemo.tsx` — full replacement for the showcase demo component.
- `showcase/app/api/gateway/chat/route.ts` — new server-side proxy route.

## Required Vercel configuration

Set this environment variable for the **showcase Next.js project** in Vercel, for Preview and Production as appropriate:

`CONTROLPLANE_GATEWAY_URL=https://YOUR-DEPLOYED-GATEWAY-DOMAIN`

Use the gateway's base URL only; do not append `/v1/chat/completions`. The proxy adds that path. HTTPS is required for non-local hosts. Redeploy the showcase after setting the variable because route configuration reads server environment at runtime, but a fresh deployment is still needed to publish the code changes.

## Behavior and boundaries

- Example buttons populate the prompt; clicking **Run request** sends a live POST.
- Tenant selection is sent as `X-ControlPlane-Tenant` and validated server-side against the three configured tenant IDs.
- Provider failures are shown as errors. The UI does not substitute prerecorded responses.
- The UI only displays a successful governed result when the response contains `controlplane.request_id`.
- The returned request ID is not treated as proof that the audit row is durably persisted. The UI explicitly says persistence is not independently verified.
- No provider API key is exposed to the browser.

## Integration note

This patch targets the repository layout in `ControlPLANE-main (6).zip`. Merge these paths into the current repository; do not replace the repository wholesale with the older ZIP snapshot. The gateway's current deployment must remain the source of truth for API behavior.
