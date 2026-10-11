import { ArrowRight } from "lucide-react";
import type { ReactNode } from "react";

/**
 * The few pieces every screen repeats. Severity colours are fixed here and
 * nowhere else: critical is danger, high is signal, medium is caution, low is
 * subtle. A screen that picks its own shade of red is how a high started
 * looking like a critical in one tab and not the other.
 */
export type Severity = "critical" | "high" | "medium" | "low";

export const SEVERITY_TEXT: Record<string, string> = {
  critical: "text-danger",
  high: "text-signal",
  medium: "text-caution",
  low: "text-subtle",
};

export const SEVERITY_DOT: Record<string, string> = {
  critical: "bg-danger",
  high: "bg-signal",
  medium: "bg-caution",
  low: "bg-subtle",
};

const SEVERITY_WASH: Record<string, string> = {
  critical: "bg-danger/10",
  high: "bg-signal/10",
  medium: "bg-caution/10",
  low: "bg-muted",
};

export function SeverityBadge({ severity, className = "" }: { severity: string; className?: string }) {
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-sm px-2 py-0.5 font-mono text-[11px] font-medium uppercase tracking-[0.04em] ${
        SEVERITY_WASH[severity] ?? SEVERITY_WASH.low
      } ${SEVERITY_TEXT[severity] ?? SEVERITY_TEXT.low} ${className}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${SEVERITY_DOT[severity] ?? SEVERITY_DOT.low}`} />
      {severity}
    </span>
  );
}

export function Technique({ id, tone = "default" }: { id: string; tone?: "default" | "alert" }) {
  return (
    <span
      className={`inline-flex shrink-0 items-center rounded-sm border px-1.5 py-px font-mono text-[11px] ${
        tone === "alert"
          ? "border-danger/30 bg-danger/10 text-danger"
          : "border-border bg-muted text-muted-foreground"
      }`}
    >
      {id}
    </span>
  );
}

export function TechniqueChain({ ids, max }: { ids: string[]; max?: number }) {
  const shown = max ? ids.slice(0, max) : ids;
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      {shown.map((t, i) => (
        <span key={`${t}-${i}`} className="inline-flex items-center gap-1">
          {i > 0 ? <ArrowRight className="h-3 w-3 text-subtle" aria-hidden /> : null}
          <Technique id={t} />
        </span>
      ))}
    </span>
  );
}

export function Segmented<T extends string>({
  items,
  value,
  onChange,
  disabled,
  label,
}: {
  items: { value: T; label: string }[];
  value: T | null;
  onChange: (value: T) => void;
  disabled?: boolean;
  label: string;
}) {
  return (
    <div role="group" aria-label={label} className="inline-flex h-8 items-center gap-0.5 rounded-sm border border-border bg-card p-0.5">
      {items.map((item) => {
        const active = item.value === value;
        return (
          <button
            key={item.value}
            type="button"
            aria-pressed={active}
            disabled={disabled}
            onClick={() => onChange(item.value)}
            className={`h-full rounded-sm px-2.5 text-[12px] transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
              active ? "bg-muted font-medium text-foreground" : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}

export function EmptyState({ icon, children }: { icon?: ReactNode; children: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-14 text-center text-[13px] text-muted-foreground">
      {icon ? <span className="text-subtle">{icon}</span> : null}
      <div className="max-w-md">{children}</div>
    </div>
  );
}
