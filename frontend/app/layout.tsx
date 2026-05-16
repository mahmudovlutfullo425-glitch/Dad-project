import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Navbar } from "@/components/Navbar";
import { Providers } from "@/components/Providers";
import "./globals.css";

export const metadata: Metadata = {
  title: "FlashShop — Flash-sale storefront",
  description:
    "Distributed e-commerce demo with real-time inventory, flash sales, and a polyglot data tier.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Providers>
          <Navbar />
          <main>{children}</main>
          <footer className="mt-12 border-t border-slate-200 bg-white py-6 text-center text-xs text-slate-500">
            FlashShop · Database Application &amp; Design · Inha University Tashkent · Spring 2026
          </footer>
        </Providers>
      </body>
    </html>
  );
}
