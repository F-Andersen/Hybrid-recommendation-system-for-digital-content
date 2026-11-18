import type { Metadata } from "next";
import { JetBrains_Mono, Manrope, Unbounded } from "next/font/google";
import Link from "next/link";

import { SiteHeader } from "@/components/SiteHeader";

import "./globals.css";

// All three families ship basic Cyrillic, so Ukrainian text never falls back.
const manrope = Manrope({
  subsets: ["latin", "cyrillic"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-sans",
});
const unbounded = Unbounded({
  subsets: ["latin", "cyrillic"],
  weight: ["500", "600"],
  variable: "--font-display",
});
const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin", "cyrillic"],
  weight: ["400"],
  variable: "--font-code",
});

export const metadata: Metadata = {
  title: { default: "Рекомендаційна система", template: "%s · Рекомендаційна система" },
  description: "Гібридні рекомендації фільмів і книг: ALS, BGE-M3, Qwen3",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="uk" className={`${manrope.variable} ${unbounded.variable} ${jetbrainsMono.variable}`}>
      <body>
        <a href="#main" className="skip-link">
          Перейти до вмісту
        </a>
        <SiteHeader />
        <main id="main" className="wrap" tabIndex={-1}>
          {children}
        </main>
        <footer className="site-footer">
          <div className="wrap footer-row">
            <span>ALS · BGE-M3 · Qwen3 8B (Ollama, локально)</span>
            <Link href="/status">Стан системи</Link>
          </div>
        </footer>
      </body>
    </html>
  );
}
