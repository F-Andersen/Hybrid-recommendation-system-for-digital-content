"use client";

import Link from "next/link";

export default function ErrorPage({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <section className="panel" aria-labelledby="error-title">
      <h1 className="section-title" id="error-title">
        <span className="mono">!!</span>
        Не вдалося завантажити сторінку
      </h1>
      <p className="notice notice-error" role="alert">
        Сервер не відповів або повернув помилку. Перевірте, що контейнери запущено, і спробуйте ще
        раз.
      </p>
      {error.digest ? <p className="mono muted">Код: {error.digest}</p> : null}
      <div className="actions">
        <button type="button" className="btn btn-primary" onClick={reset}>
          Спробувати ще раз
        </button>
        <Link href="/status" className="btn">
          Стан системи
        </Link>
      </div>
    </section>
  );
}
