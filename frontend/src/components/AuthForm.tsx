"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { apiSend, errorMessage, safeNext } from "@/lib/client-api";
import type { UserProfile } from "@/lib/types";

type Props = { mode: "login" | "register"; next?: string };

export function AuthForm({ mode, next }: Props) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isRegister = mode === "register";

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const payload: Record<string, string> = {
      email: String(form.get("email") ?? ""),
      password: String(form.get("password") ?? ""),
    };
    if (isRegister) payload.display_name = String(form.get("display_name") ?? "");

    setBusy(true);
    setError(null);
    try {
      await apiSend<UserProfile>("POST", isRegister ? "/auth/register" : "/auth/login", payload);
      router.replace(isRegister ? "/onboarding" : safeNext(next));
      router.refresh();
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  const errorId = `${mode}-error`;
  return (
    <form className="form" onSubmit={submit} noValidate={false} aria-describedby={error ? errorId : undefined}>
      {isRegister ? (
        <div className="field">
          <label className="field-label" htmlFor="display_name">
            Ім&apos;я
          </label>
          <input
            className="input"
            id="display_name"
            name="display_name"
            autoComplete="nickname"
            required
            maxLength={80}
          />
        </div>
      ) : null}
      <div className="field">
        <label className="field-label" htmlFor="email">
          Електронна пошта
        </label>
        <input
          className="input"
          id="email"
          name="email"
          type="email"
          autoComplete="email"
          inputMode="email"
          required
          maxLength={254}
          aria-invalid={error ? true : undefined}
        />
      </div>
      <div className="field">
        <label className="field-label" htmlFor="password">
          Пароль
        </label>
        <input
          className="input"
          id="password"
          name="password"
          type="password"
          autoComplete={isRegister ? "new-password" : "current-password"}
          required
          minLength={isRegister ? 8 : 1}
          maxLength={128}
          aria-describedby={isRegister ? "password-hint" : undefined}
          aria-invalid={error ? true : undefined}
        />
        {isRegister ? (
          <span className="field-hint" id="password-hint">
            Щонайменше 8 символів
          </span>
        ) : null}
      </div>
      <p className="notice notice-error" id={errorId} role="alert" hidden={!error}>
        {error}
      </p>
      <div>
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? "Зачекайте…" : isRegister ? "Зареєструватися" : "Увійти"}
        </button>
      </div>
    </form>
  );
}
