import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "OpenAudit — Flight Recorder",
  description: "Open-source SIEM flight recorder for AI agent tool-use",
  icons: { icon: "/openaudit-icon-white.svg", apple: "/openaudit-icon-white.svg" },
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
