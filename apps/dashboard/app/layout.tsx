import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AgentAudit — Flight Recorder",
  description: "Local flight recorder for governed AI agents — tool calls, denials, and approvals",
  icons: { icon: "/blackbox-logo.png", apple: "/blackbox-logo.png" },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="antialiased">
        {children}
      </body>
    </html>
  );
}
