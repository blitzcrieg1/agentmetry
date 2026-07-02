import { ORCHESTRATOR_URL } from "@/lib/utils";

export function apiHeaders(): HeadersInit {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  const apiKey = process.env.NEXT_PUBLIC_BLACKBOX_API_KEY;
  if (apiKey) {
    headers["X-API-Key"] = apiKey;
  }
  return headers;
}

export async function apiPost(path: string, body?: unknown) {
  const res = await fetch(`${ORCHESTRATOR_URL}${path}`, {
    method: "POST",
    headers: apiHeaders(),
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `Request failed: ${res.status}`);
  }
  return res.json();
}
