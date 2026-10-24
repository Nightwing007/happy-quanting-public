import { Suspense } from "react";
import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";
import { SiteHeader } from "@/components/site-header";
import { BackendStatusBanner } from "@/components/backend-status-banner";
import { DataNotice } from "@/components/data-notice";
import { BadgeWatcher } from "@/components/badges/badge-watcher";

// The variable is named --font-sans because globals.css (shadcn) reads that name.
const geistSans = Geist({
  variable: "--font-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
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
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <Providers>
          {/* The header reads the path, which on a dynamic route (/sim/[id]) is only known per request. */}
          <Suspense fallback={<header className="sticky top-0 z-40 h-14 border-b bg-background/90" />}>
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
