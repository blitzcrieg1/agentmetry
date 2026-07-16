import type { Metadata } from "next";
import "./globals.css";
import { ThemeProvider } from "@/components/theme-provider";

export const metadata: Metadata = {
  title: "Agentmetry — SIEM",
  description: "Enterprise flight recorder for AI agent tool-use",
  icons: { icon: "/agentmetry-icon-white.svg", apple: "/agentmetry-icon-white.svg" },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="antialiased bg-black text-white font-mono selection:bg-emerald-500/30">
        <ThemeProvider attribute="class" defaultTheme="dark" enableSystem={false} forcedTheme="dark">
          {children}
        </ThemeProvider>
      </body>
    </html>
  );
}
