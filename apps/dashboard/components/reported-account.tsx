"use client";

import { accountSourceLabel } from "@/lib/identity";

export type ReportedAccountClaim = {
  domain?: string;
  source?: string;
  organization_id?: string;
  account_id?: string;
  user_id?: string;
};

export function ReportedAccount({ account }: { account?: ReportedAccountClaim }) {
  const hint = account?.source === "local_config"
    ? "Last sign-in on this machine; it may differ from the account used for this call."
    : account?.source === "codex_auth"
      ? "The domain is read from the local sign-in file, and its token signature is not verified. Any IDs come from the session file, so the two can differ if the sign-in changed."
      : "A reported claim, not proof of who made this call.";
  return (
    <section className="rounded-md border border-border bg-muted/30 p-3" aria-label="Reported account">
      <h3 className="eyebrow">Reported account</h3>
      {account && Object.keys(account).length ? (
        <>
          <p className="mt-1 break-all font-mono text-[13px] font-medium">{account.domain || "No domain reported"}</p>
          <p className="mt-1 text-[12px] text-muted-foreground">{accountSourceLabel(account.source ?? "") || "Source not stated"}</p>
          <dl className="mt-2 space-y-1 text-[12px]">
            {([['Organization ID', account.organization_id], ['Account ID', account.account_id], ['User ID', account.user_id]] as const).filter(([, value]) => value).map(([label, value]) => (
              <div key={label}><dt className="text-muted-foreground">{label}{account.source === "codex_auth" ? " (session file)" : ""}</dt><dd className="break-all font-mono">{value}</dd></div>
            ))}
          </dl>
          <p className="mt-2 text-[12px] leading-relaxed text-muted-foreground">{hint}</p>
        </>
      ) : <p className="mt-1 text-[13px] text-muted-foreground">Unknown. This event carried no account claim.</p>}
    </section>
  );
}
