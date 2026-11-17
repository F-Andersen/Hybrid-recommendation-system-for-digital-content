import Link from "next/link";

type Tab = { href: string; label: string; active: boolean };

export function Tabs({ tabs, label }: { tabs: Tab[]; label: string }) {
  return (
    <nav aria-label={label}>
      <ul className="tabs">
        {tabs.map((tab) => (
          <li key={tab.href}>
            <Link href={tab.href} aria-current={tab.active ? "page" : undefined}>
              {tab.label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
