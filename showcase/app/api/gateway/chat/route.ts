import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const ALLOWED_TENANTS = new Set(["customer_support", "internal_copilot", "regulated_agent"]);
const MAX_BODY_BYTES = 32_000;

function gatewayUrl(): string | null {
  const configured = process.env.CONTROLPLANE_GATEWAY_URL?.trim();
  if (!configured) return null;
  try {
    const url = new URL(configured);
    if (url.protocol !== "https:" && url.hostname !== "localhost" && url.hostname !== "127.0.0.1") return null;
    return url.toString().replace(/\/$/, "");
  } catch {
    return null;
  }
}

export async function POST(request: NextRequest) {
  const baseUrl = gatewayUrl();
  if (!baseUrl) {
    return NextResponse.json(
      { detail: "Live playground is not configured. Set CONTROLPLANE_GATEWAY_URL to the HTTPS base URL of the deployed gateway." },
      { status: 503 },
    );
  }

  const tenant = request.headers.get("x-controlplane-tenant") ?? "customer_support";
  if (!ALLOWED_TENANTS.has(tenant)) {
    return NextResponse.json({ detail: "Unknown tenant policy." }, { status: 400 });
  }

  const rawBody = await request.text();
  if (new TextEncoder().encode(rawBody).byteLength > MAX_BODY_BYTES) {
    return NextResponse.json({ detail: "Request body is too large." }, { status: 413 });
  }

  let body: unknown;
  try {
    body = JSON.parse(rawBody);
  } catch {
    return NextResponse.json({ detail: "Request body must be valid JSON." }, { status: 400 });
  }
  if (!body || typeof body !== "object" || !Array.isArray((body as { messages?: unknown }).messages)) {
    return NextResponse.json({ detail: "Request must include a messages array." }, { status: 400 });
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 125_000);
  try {
    const upstream = await fetch(`${baseUrl}/v1/chat/completions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-ControlPlane-Tenant": tenant,
        "X-Request-ID": crypto.randomUUID(),
      },
      body: JSON.stringify(body),
      cache: "no-store",
      signal: controller.signal,
    });
    const responseText = await upstream.text();
    let parsed: unknown;
    try {
      parsed = JSON.parse(responseText);
    } catch {
      parsed = { detail: responseText.slice(0, 2000) || "Gateway returned a non-JSON response." };
    }
    return NextResponse.json(parsed, {
      status: upstream.status,
      headers: { "Cache-Control": "no-store" },
    });
  } catch (error) {
    const isTimeout = error instanceof Error && error.name === "AbortError";
    return NextResponse.json(
      { detail: isTimeout ? "The gateway request timed out." : "Could not connect to the configured ControlPlane gateway." },
      { status: isTimeout ? 504 : 502 },
    );
  } finally {
    clearTimeout(timeout);
  }
}
