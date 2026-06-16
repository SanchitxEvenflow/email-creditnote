import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import Sidebar from "../components/Sidebar";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Evenflow Internal Tools",
  description: "Internal tools for Evenflow operations",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full">
      <body className={`${inter.className} min-h-full bg-slate-50 flex`}>
        <Sidebar />
        <main className="flex-1 ml-64 min-h-screen relative flex flex-col">
          {children}
        </main>
      </body>
    </html>
  );
}
