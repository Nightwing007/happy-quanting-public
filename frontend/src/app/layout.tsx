import { Suspense } from "react";
import type { Metadata } from "next";
import { Anton, Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";
import { SiteHeader } from "@/components/site-header";
import { BackendStatusBanner } from "@/components/backend-status-banner";
import { DataNotice } from "@/components/data-notice";
import { BadgeWatcher } from "@/components/badges/badge-watcher";

// Display: Anton (400, uppercase) for page titles only. Body: Inter. Labels and numbers: JetBrains Mono.
const display = Anton({
  variable: "--font-display-face",
  subsets: ["latin"],
  weight: "400",
});

const body = Inter({
  variable: "--font-body",
  subsets: ["latin"],
});

const mono = JetBrains_Mono({
  variable: "--font-mono-face",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Happy Quanting",
  description: "A paper-trading playground with realistic costs and rules.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${display.variable} ${body.variable} ${mono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <Providers>
          {/* The header reads the path, which on a dynamic route (/sim/[id]) is only known per request. */}
          <Suspense fallback={<header className="sticky top-0 z-40 h-14 border-b border-transparent" />}>
            <SiteHeader />
          </Suspense>
          <BadgeWatcher />
          <BackendStatusBanner />
          <main className="mx-auto w-full max-w-7xl min-w-0 flex-1 px-4 py-6">{children}</main>
          <Suspense fallback={null}>
            <DataNotice />
          </Suspense>
        </Providers>
      </body>
    </html>
  );
}
