import { ORCHESTRATOR_URL } from "@/lib/utils";

/**
 * Headers for every call to the local API.
 *
 * The dashboard holds no API key. It used to compile one into the bundle
 * (NEXT_PUBLIC_AGENTMETRY_API_KEY), where anyone who could load the page could
 * read it. It now rides on an HttpOnly session cookie that `agentmetry
 * dashboard` sets through a one-time link, so every fetch sends
 * `credentials: "include"`. `X-Agentmetry-Request` is the CSRF guard: a
 * cross-site form cannot send a custom header, and the API refuses a
 * cookie-authenticated write without it.
 */
export function apiHeaders(): HeadersInit {
  return {
    "Content-Type": "application/json",
    "X-Agentmetry-Request": "1",
  };
}

export async function apiPost(path: string, body?: unknown) {
  const res = await fetch(`${ORCHESTRATOR_URL}${path}`, {
    method: "POST",
    headers: apiHeaders(),
    credentials: "include",
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `Request failed: ${res.status}`);
  }
  return res.json();
}
