"use client";

import * as React from "react";
import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";

const ROW =
  "flex h-9 items-center justify-center gap-2.5 rounded-sm text-[13px] text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground lg:justify-start lg:px-2.5";

export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = React.useState(false);

  React.useEffect(() => setMounted(true), []);

  if (!mounted) {
    return (
      <span className={ROW}>
        <Sun className="h-4 w-4 shrink-0 opacity-40" />
        <span className="hidden lg:inline">Theme</span>
      </span>
    );
  }

  const isDark = resolvedTheme === "dark";

  return (
    <button
      type="button"
      onClick={() => setTheme(isDark ? "light" : "dark")}
      className={ROW}
      title={isDark ? "Switch to light mode" : "Switch to dark mode"}
    >
      {isDark ? <Sun className="h-4 w-4 shrink-0" /> : <Moon className="h-4 w-4 shrink-0" />}
      <span className="hidden lg:inline">{isDark ? "Light mode" : "Dark mode"}</span>
    </button>
  );
}
