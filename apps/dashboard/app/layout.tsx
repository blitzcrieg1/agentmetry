import type { Metadata } from "next";
import "@fontsource/ibm-plex-sans/latin-400.css";
import "@fontsource/ibm-plex-sans/latin-500.css";
import "@fontsource/ibm-plex-sans/latin-600.css";
import "@fontsource/ibm-plex-mono/latin-400.css";
import "@fontsource/ibm-plex-mono/latin-500.css";
import "./globals.css";
import { ThemeProvider } from "@/components/theme-provider";

// The agentmetry.ai typefaces, from the same @fontsource packages the site
// uses. They install with npm and ship inside the export, so neither the build
// nor the running dashboard reaches a font CDN. next/font/google was tried
// first: it downloads at build time, and that step failed in CI.

export const metadata: Metadata = {
  title: "Agentmetry",
  description: "Local flight recorder for AI coding agents",
  icons: { icon: "/agentmetry-icon-white.svg", apple: "/agentmetry-icon-white.svg" },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="font-sans antialiased">
        <ThemeProvider attribute="class" defaultTheme="dark" enableSystem storageKey="agentmetry-theme">
          {children}
        </ThemeProvider>
      </body>
    </html>
  );
}
