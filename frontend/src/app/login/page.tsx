import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { AuthForm } from "@/components/AuthForm";
import { Section } from "@/components/Section";
import { getMe } from "@/lib/api";
import { safeNext } from "@/lib/client-api";
import { pickText } from "@/lib/format";

export const metadata: Metadata = { title: "Вхід" };

type Props = { searchParams: Promise<Record<string, string | string[] | undefined>> };

export default async function LoginPage({ searchParams }: Props) {
  const params = await searchParams;
  const next = safeNext(pickText(params, "next"));
  if (await getMe()) redirect(next);

  return (
    <>
      <h1 className="page-title">Вхід</h1>
      <div className="auth-layout">
        <Section number={1} title="Обліковий запис">
          <AuthForm mode="login" next={next} />
        </Section>
        <Section number={2} title="Немає облікового запису">
          <p>
            Після реєстрації ви оціните кілька фільмів або книг, і система одразу побудує перші
            персональні рекомендації.
          </p>
          <div className="actions">
            <Link href="/register" className="btn">
              Зареєструватися
            </Link>
          </div>
        </Section>
      </div>
    </>
  );
}
