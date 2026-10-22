import { apiHeaders } from "@/lib/api";
import { ORCHESTRATOR_URL } from "@/lib/utils";

/**
 * Whether this browser is signed in to the local API.
 *
 * The dashboard holds no key. `agentmetry dashboard` hands the browser a
 * one-time link that sets an HttpOnly session cookie, good for 12 hours and
 * kept only in the recorder's memory, so a restart signs every browser out.
 * Before this existed, a signed-out page fired every request, got a 401 from
 * each, listed them all as failures and left every tile on "Loading".
 */
export type SessionState = "checking" | "signed_in" | "signed_out" | "unreachable";

/**
 * The session, and whether the server says its trail is a demo. `demo` is
 * null until a signed-in answer arrives: the page claims neither "this
 * machine" nor "sample data" before the server has said which it is.
 */
export async function readSession(): Promise<{ state: SessionState; demo: boolean | null }> {
  try {
    const res = await fetch(`${ORCHESTRATOR_URL}/api/v1/audit/status`, {
      headers: apiHeaders(),
      credentials: "include",
    });
    if (res.status === 401) return { state: "signed_out", demo: null };
    if (!res.ok) return { state: "unreachable", demo: null };
    let demo = false;
    try {
      demo = (await res.json())?.demo === true;
    } catch {
      /* an older server without the field is not a demo */
    }
    return { state: "signed_in", demo };
  } catch {
    return { state: "unreachable", demo: null };
  }
}

export async function checkSession(): Promise<SessionState> {
  return (await readSession()).state;
}

/**
 * Revoke this browser's session on the server and drop its cookie. The server
 * forgets the session whether or not the response arrives, so the caller
 * treats the browser as signed out either way.
 */
export async function signOut(): Promise<void> {
  try {
    await fetch(`${ORCHESTRATOR_URL}/api/v1/auth/logout`, {
      method: "POST",
      headers: apiHeaders(),
      credentials: "include",
    });
  } catch {
    /* signed out locally regardless; the next check says what the server thinks */
  }
}
