import { apiHeaders } from "@/lib/api";
import { ORCHESTRATOR_URL } from "@/lib/utils";

/**
 * The four-week beta gate. Mirrors core/audit/dogfood.py.
 *
 * This lives in the dashboard because the gate went weeks unstarted, and the
 * reason was friction rather than intent: a criterion you have to remember to
 * run a command for is one you stop running. Seeing it beside the analytics you
 * already open is the point.
 */

export type Verdict = "GREEN" | "RED" | "IN PROGRESS";

export interface DogfoodWeek {
  index: number;
  start: string;
  end: string;
  events: number;
  active_days: number;
  sessions: number;
  detections: number;
  untriaged: number;
  complete: boolean;
  verdict: Verdict;
  reasons: string[];
}

export interface DogfoodReport {
  started: string | null;
  consecutive_green: number;
  required: number;
  passed: boolean;
  chain_ok: boolean;
  chain_message: string;
  spooled: number;
  weeks: DogfoodWeek[];
}

export const VERDICT_CHIP: Record<Verdict, string> = {
  GREEN: "bg-emerald-500/15 text-emerald-700 ring-emerald-500/30 dark:text-emerald-300",
  RED: "bg-red-500/15 text-red-700 ring-red-500/30 dark:text-red-300",
  "IN PROGRESS": "bg-sky-500/15 text-sky-700 ring-sky-500/30 dark:text-sky-300",
};

/** Weeks still to go. Never negative, and zero once the gate is met. */
export function weeksRemaining(report: DogfoodReport): number {
  return Math.max(0, report.required - report.consecutive_green);
}

/**
 * Whether anything needs the operator's attention right now.
 *
 * Deliberately not "the gate has not passed yet". On day one nothing is wrong,
 * and a panel that shouts on day one gets ignored by day three.
 */
export function needsAttention(report: DogfoodReport): boolean {
  if (!report.started) return false;
  if (!report.chain_ok || report.spooled > 0) return true;
  return report.weeks.some((w) => w.complete && w.verdict === "RED");
}

export async function fetchDogfood(): Promise<DogfoodReport> {
  const res = await fetch(`${ORCHESTRATOR_URL}/api/v1/audit/dogfood`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as DogfoodReport;
}
