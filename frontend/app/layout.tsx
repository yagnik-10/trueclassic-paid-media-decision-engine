import "./globals.css";
import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "True Classic — Paid Media Decision Engine",
  description: "Stage 1 thin shell: recommendation review & approval.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <nav className="nav">
          <span className="brand">True Classic · Paid Media</span>
          <a href="/ingestion">Ingestion &amp; reconciliation</a>
          <a href="/">Recommendation</a>
        </nav>
        {children}
      </body>
    </html>
  );
}
