import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans, IBM_Plex_Sans_Condensed } from "next/font/google";
import Link from "next/link";

import { SiteHeader } from "@/components/SiteHeader";

import "./globals.css";

const plexSans = IBM_Plex_Sans({
  subsets: ["latin", "cyrillic"],
  weight: ["400", "500", "600"],
  variable: "--font-sans",
});
// Plex Sans Condensed has no basic Cyrillic (U+0400-045F); Ukrainian glyphs fall back
// to Plex Sans via the --condensed font stack in globals.css.
const plexCondensed = IBM_Plex_Sans_Condensed({
  subsets: ["latin"],
  weight: ["500", "600"],
  variable: "--font-condensed",
});
const plexMono = IBM_Plex_Mono({
  subsets: ["latin", "cyrillic"],
  weight: ["400", "500"],
  variable: "--font-mono",
});

export const metadata: Metadata = {
  title: { default: "Рекомендаційна система", template: "%s · Рекомендаційна система" },
  description: "Гібридні рекомендації фільмів і книг: ALS, BGE-M3, Qwen3",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="uk" className={`${plexSans.variable} ${plexCondensed.variable} ${plexMono.variable}`}>
      <body>
        <a href="#main" className="skip-link">
          Перейти до вмісту
        </a>
        <SiteHeader />
        <main id="main" className="wrap" tabIndex={-1}>
          {children}
        </main>
        <footer className="site-footer">
          <div className="wrap footer-row mono">
            <span>ALS · BGE-M3 · Qwen3 8B (Ollama, локально)</span>
            <Link href="/status">Стан системи</Link>
          </div>
        </footer>
      </body>
    </html>
  );
}
