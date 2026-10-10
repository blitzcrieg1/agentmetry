import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";
import "./globals.css";
import { ThemeProvider } from "@/components/theme-provider";

// The agentmetry.ai typefaces. next/font downloads them at build time and
// serves them from the export, so the dashboard still makes no request off
// the machine at runtime.
const plexSans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-plex-sans",
  display: "swap",
});
const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-plex-mono",
  display: "swap",
});

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
    <html lang="en" suppressHydrationWarning className={`${plexSans.variable} ${plexMono.variable}`}>
      <body className="font-sans antialiased">
        <ThemeProvider attribute="class" defaultTheme="dark" enableSystem storageKey="agentmetry-theme">
          {children}
        </ThemeProvider>
      </body>
    </html>
  );
}
