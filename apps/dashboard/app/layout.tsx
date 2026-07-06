import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "BLACKBOX — Agentic OS",
  description: "Obsidian-Cortex State Machine Execution Environment",
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
