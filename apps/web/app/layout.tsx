import type { Metadata } from "next";
import { Geist, Geist_Mono, IBM_Plex_Sans_Arabic } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "@/lib/auth-context";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
  // We set font-family ourselves in globals.css and list an Arabic font next
  // to Geist, so Next's metric-matched auto fallback is dead CSS that only
  // adds weight. The real fallback (Plex Arabic) is declared below.
  adjustFontFallback: false,
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
  adjustFontFallback: false,
});

// Geist ships no Arabic glyphs, so without this the browser silently substitutes
// a system font and the Arabic text renders smaller than the Latin beside it.
// Listed after Geist in the stack, so Latin still uses Geist.
const plexArabic = IBM_Plex_Sans_Arabic({
  variable: "--font-arabic",
  subsets: ["arabic"],
  weight: ["400", "500", "600", "700"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Sayvors",
  description: "EVERY LINE. ONE VOICE",
  icons: "/Sayvors_Icon.png",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      // I18nProvider syncs lang/dir to the chosen locale on the client; the
      // initial values match DEFAULT_LOCALE so first paint is correct for the
      // common case and there is no hydration mismatch.
      lang="en"
      dir="ltr"
      className={`${geistSans.variable} ${geistMono.variable} ${plexArabic.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
