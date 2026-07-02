import type { Metadata } from "next";
import "./globals.css";
import { MissionControl } from "@/components/mission-control";

export const metadata: Metadata = {
  title: "BLACKBOX — Agentic OS",
  description: "Obsidian-Cortex State Machine Execution Environment",
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
