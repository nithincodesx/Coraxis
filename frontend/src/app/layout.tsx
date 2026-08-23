import type { Metadata } from "next";
import { Inter, Plus_Jakarta_Sans } from "next/font/google";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
});

const plusJakartaSans = Plus_Jakarta_Sans({
  subsets: ["latin"],
  variable: "--font-display",
});

export const metadata: Metadata = {
  title: "Coraxis — Autonomous Multi-Agent Research Laboratory",
  description: "Watch four specialized AI agents research topics live: search, cross-check sources, reason through findings, and generate structured cited reports.",
  keywords: ["AI agents", "CrewAI", "Multi-Agent Research", "Groq", "Deep Research", "Coraxis"],
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${plusJakartaSans.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-[#f4f6f9] text-[#0f172a]">{children}</body>
    </html>
  );
}
