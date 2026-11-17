import Link from "next/link";

import { formatInt } from "@/lib/format";

type Props = {
  page: number;
  pageSize: number;
  total: number;
  href: (page: number) => string;
  label?: string;
};

export function Pagination({ page, pageSize, total, href, label = "Сторінки" }: Props) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (pages <= 1) return null;
  const current = Math.min(page, pages);

  return (
    <nav className="pagination" aria-label={label}>
      {current > 1 ? (
        <Link className="btn btn-small" href={href(current - 1)} rel="prev">
          Попередня
        </Link>
      ) : (
        <span className="btn btn-small" aria-disabled="true">
          Попередня
        </span>
      )}
      <span className="mono pagination-info">
        {formatInt(current)} / {formatInt(pages)}
      </span>
      {current < pages ? (
        <Link className="btn btn-small" href={href(current + 1)} rel="next">
          Наступна
        </Link>
      ) : (
        <span className="btn btn-small" aria-disabled="true">
          Наступна
        </span>
      )}
    </nav>
  );
}
