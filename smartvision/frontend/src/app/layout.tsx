import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "SmartVision — Autonomous Operator Dashboard",
  description: "Next.js Command & Control Dashboard for SmartVision Autonomous Pan-Tilt Person Tracking System",
  icons: {
    icon: "/favicon.ico",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-slate-950 text-slate-100 antialiased selection:bg-emerald-500/30">
        {children}
      </body>
    </html>
  );
}
