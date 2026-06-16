"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";

export default function Sidebar() {
  const pathname = usePathname();

  const links = [
    { name: "Credit Notes", href: "/credit-notes", icon: "📧" },
    { name: "GRN Push", href: "/grn-push", icon: "📦" },
  ];

  return (
    <div className="w-64 bg-slate-900 min-h-screen flex flex-col fixed left-0 top-0 text-slate-300 shadow-xl z-50">
      <div className="p-6 flex items-center justify-center border-b border-white/5">
        <Image src="/logo.png" className="h-12 w-auto object-contain" alt="Evenflow logo" width={160} height={64} priority />
      </div>
      <div className="flex-1 py-8 px-4 flex flex-col gap-2">
        <div className="px-4 text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">Tools</div>
        {links.map((link) => {
          const isActive = pathname.startsWith(link.href);
          return (
            <Link
              key={link.name}
              href={link.href}
              className={`flex items-center gap-3 px-4 py-3 rounded-xl transition-all ${
                isActive
                  ? "bg-indigo-500/10 text-indigo-400 font-medium"
                  : "hover:bg-white/5 hover:text-white font-medium"
              }`}
            >
              <span className="text-xl">{link.icon}</span>
              <span>{link.name}</span>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
