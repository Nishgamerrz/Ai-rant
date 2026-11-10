import "./globals.css";
import type { Metadata } from "next";
import { AuthGate } from "@/components/AuthGate";

export const metadata: Metadata = {
  title: "NishAgent — AI Studio",
  description: "Chat with NishAgent (GitHub workflow agent) and launch Roblox shorts — nishagent.vercel.app",
  metadataBase: new URL("https://nishagent.vercel.app"),
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-ink text-zinc-100 antialiased">
        <AuthGate>{children}</AuthGate>
      </body>
    </html>
  );
}
