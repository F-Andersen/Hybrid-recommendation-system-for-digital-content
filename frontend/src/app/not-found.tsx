import Link from "next/link";

export default function NotFound() {
  return (
    <section className="panel" aria-labelledby="nf-title">
      <h1 className="section-title" id="nf-title">
        <span className="mono">404</span>
        Сторінку не знайдено
      </h1>
      <p>Такого запису немає в каталозі, або посилання застаріло.</p>
      <div className="actions">
        <Link href="/catalog" className="btn btn-primary">
          До каталогу
        </Link>
        <Link href="/" className="btn">
          На головну
        </Link>
      </div>
    </section>
  );
}
