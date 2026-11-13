import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans, IBM_Plex_Sans_Condensed } from "next/font/google";
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
  title: "Рекомендаційна система",
  description: "Гібридні рекомендації фільмів і книг: ALS, BGE-M3, Qwen3",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="uk" className={`${plexSans.variable} ${plexCondensed.variable} ${plexMono.variable}`}>
      <body>
        <header className="site-header">
          <div className="wrap">
            <span className="brand">Рекомендаційна система</span>
            <span className="mono muted">фільми · книги</span>
          </div>
        </header>
        <main className="wrap">{children}</main>
      </body>
    </html>
  );
}
