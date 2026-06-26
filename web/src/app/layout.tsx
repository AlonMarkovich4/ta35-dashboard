import type { Metadata } from "next";
import { Heebo } from "next/font/google";
import { AppShell } from "@/components/AppShell";
import "./globals.css";

const heebo = Heebo({
  subsets: ["hebrew", "latin"],
  variable: "--font-heebo",
  weight: ["400", "500", "600", "700"],
});

export const metadata: Metadata = {
  title: "TA-35 Dashboard",
  description: "TA-35 Expiry Intelligence Dashboard",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="he" dir="rtl" className={`${heebo.variable} h-full`}>
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html:
              `try{if(localStorage.getItem('theme')==='light')document.documentElement.classList.add('light')}catch(e){}`,
          }}
        />
      </head>
      <body className="min-h-full antialiased">
        <div className="relative z-10">
          <AppShell>{children}</AppShell>
        </div>
      </body>
    </html>
  );
}
