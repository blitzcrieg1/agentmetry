"use client";

import { useState } from "react";
import { Check, Copy, KeyRound, RefreshCw } from "lucide-react";

const COMMAND = "agentmetry dashboard";
const CHECKOUT_COMMAND = "python -m agentmetry.cli dashboard";

/**
 * What a browser without a session sees, in place of every page. It replaces a
 * page that fired every request anyway and showed each 401 as a failure.
 */
export function SignedOut({ onCheckAgain, justSignedOut }: { onCheckAgain: () => void; justSignedOut: boolean }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(COMMAND);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* the command is on screen to type; copying is a convenience */
    }
  };

  return (
    <div className="flex flex-1 items-start justify-center overflow-y-auto py-10">
      <section className="panel w-full max-w-xl space-y-5 p-6" aria-labelledby="signed-out-title">
        <div className="flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-sm border border-border bg-background">
            <KeyRound className="h-5 w-5 text-muted-foreground" aria-hidden />
          </span>
          <div>
            <h2 id="signed-out-title" className="text-[17px] font-semibold">
              {justSignedOut ? "You are signed out" : "This browser is not signed in"}
            </h2>
            <p className="text-[13px] text-muted-foreground">Recording carries on either way. Only this page is locked.</p>
          </div>
        </div>

        <div className="space-y-2">
          <p className="text-[13px] leading-relaxed text-muted-foreground">
            Run this on this machine. It opens a one-time link that signs this browser in for 12 hours.
          </p>
          <div className="flex items-center gap-2">
            <code className="flex-1 rounded-sm border border-border bg-background px-3 py-2 font-mono text-[13px]">{COMMAND}</code>
            <button type="button" className="btn" onClick={() => void copy()} aria-label="Copy the command">
              {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
          <p className="text-[12px] text-subtle">
            From a source checkout, run <code className="font-mono">{CHECKOUT_COMMAND}</code> in apps/orchestrator.
          </p>
        </div>

        <ul className="space-y-1 text-[12px] leading-relaxed text-muted-foreground">
          <li>The link works once and expires after 2 minutes.</li>
          <li>Restarting the recorder signs every browser out; run the command again.</li>
          <li>The dashboard never holds the API key. The session lives in an HttpOnly cookie.</li>
        </ul>

        <button type="button" className="btn" onClick={onCheckAgain}>
          <RefreshCw className="h-3.5 w-3.5" />
          I have signed in, check again
        </button>
      </section>
    </div>
  );
}
