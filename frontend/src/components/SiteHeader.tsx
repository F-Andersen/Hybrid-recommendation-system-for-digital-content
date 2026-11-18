import Link from "next/link";

import { getMe } from "@/lib/api";

import { LogoutButton } from "./LogoutButton";
import { NavLinks } from "./NavLinks";

export async function SiteHeader() {
  const me = await getMe();
  const nav = [
    { href: "/", label: "Головна" },
    { href: "/catalog", label: "Каталог" },
    ...(me
      ? [
          { href: "/recommendations", label: "Рекомендації" },
          { href: "/profile", label: "Профіль" },
        ]
      : []),
    { href: "/evaluation", label: "Оцінювання" },
  ];

  return (
    <header className="site-header">
      <div className="wrap header-row">
        <Link href="/" className="brand">
          Рекомендаційна система
        </Link>
        <nav aria-label="Основна навігація">
          <NavLinks items={nav} />
        </nav>
        <div className="user-box">
          {me ? (
            <>
              <span className="mono user-name" title={me.email}>
                {me.display_name}
              </span>
              <LogoutButton />
            </>
          ) : (
            <>
              <Link href="/login" className="btn btn-small">
                Увійти
              </Link>
              <Link href="/register" className="btn btn-small btn-primary">
                Реєстрація
              </Link>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
