"use client";

import type { ReactNode } from "react";

/** Lightweight JSON syntax highlight — no extra dependencies. */
export function AuditJsonView({ value }: { value: unknown }) {
  const text = JSON.stringify(value, null, 2);
  const lines = text.split("\n");

  return (
    <pre className="max-h-48 overflow-auto text-xs leading-relaxed">
      {lines.map((line, i) => (
        <div key={i} className="whitespace-pre">
          {colorizeLine(line)}
        </div>
      ))}
    </pre>
  );
}

function colorizeLine(line: string): ReactNode {
  const keyMatch = line.match(/^(\s*)"([^"]+)":(.*)$/);
  if (keyMatch) {
    const [, indent, key, rest] = keyMatch;
    return (
      <>
        {indent}
        <span className="text-sky-400">&quot;{key}&quot;</span>
        <span className="text-zinc-500 dark:text-zinc-500">:</span>
        {colorizeValue(rest)}
      </>
    );
  }
  return <span className="text-zinc-500 dark:text-zinc-600 dark:text-zinc-400">{line}</span>;
}

function colorizeValue(fragment: string): ReactNode {
  const trimmed = fragment.trim();
  if (trimmed.startsWith('"')) {
    const str = trimmed.match(/^("(?:\\.|[^"\\])*")(.*)$/);
    if (str) {
      return (
        <>
          <span className="text-emerald-400/90">{str[1]}</span>
          <span className="text-zinc-500 dark:text-zinc-500">{str[2]}</span>
        </>
      );
    }
  }
  if (/^-?\d/.test(trimmed)) {
    return <span className="text-amber-300/90">{fragment}</span>;
  }
  if (trimmed === "true" || trimmed === "false" || trimmed.startsWith("true,") || trimmed.startsWith("false,")) {
    return <span className="text-violet-700 dark:text-violet-300/90">{fragment}</span>;
  }
  if (trimmed === "null" || trimmed.startsWith("null,")) {
    return <span className="text-zinc-500 dark:text-zinc-500">{fragment}</span>;
  }
  return <span className="text-zinc-500 dark:text-zinc-600 dark:text-zinc-400">{fragment}</span>;
}
