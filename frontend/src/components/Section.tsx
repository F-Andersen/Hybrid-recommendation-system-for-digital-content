import type { ReactNode } from "react";

import { pad2 } from "@/lib/format";

type Props = {
  number: number;
  title: string;
  aside?: ReactNode;
  children: ReactNode;
  id?: string;
};

/** Numbered document section: 2px rule on top, mono number, condensed uppercase title. */
export function Section({ number, title, aside, children, id }: Props) {
  const headingId = id ?? `section-${number}`;
  return (
    <section className="panel" aria-labelledby={headingId}>
      <div className="section-head">
        <h2 className="section-title" id={headingId}>
          <span className="mono">{pad2(number)}</span>
          {title}
        </h2>
        {aside ? <div className="section-aside">{aside}</div> : null}
      </div>
      {children}
    </section>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty mono">{children}</p>;
}

export function Notice({ tone, children }: { tone: "ok" | "warn" | "error"; children: ReactNode }) {
  return (
    <p className={`notice notice-${tone}`} role={tone === "error" ? "alert" : "status"}>
      {children}
    </p>
  );
}
