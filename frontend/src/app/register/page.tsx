import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { AuthForm } from "@/components/AuthForm";
import { Section } from "@/components/Section";
import { getMe } from "@/lib/api";

export const metadata: Metadata = { title: "Реєстрація" };

export default async function RegisterPage() {
  if (await getMe()) redirect("/onboarding");

  return (
    <>
      <h1 className="page-title">Реєстрація</h1>
      <div className="auth-layout">
        <Section number={1} title="Новий обліковий запис">
          <AuthForm mode="register" />
        </Section>
        <Section number={2} title="Що далі">
          <dl className="spec">
            <dt>Крок 1</dt>
            <dd>Оцініть щонайменше 5 фільмів або книг за шкалою 1–10.</dd>
            <dt>Крок 2</dt>
            <dd>Гібрид ALS і контентної моделі підбере кандидатів.</dd>
            <dt>Крок 3</dt>
            <dd>Локальна модель Qwen3 пояснить кожну рекомендацію.</dd>
          </dl>
          <p className="muted">
            Уже зареєстровані? <Link href="/login">Увійти</Link>
          </p>
        </Section>
      </div>
    </>
  );
}
