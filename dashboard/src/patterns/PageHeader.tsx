import type { ReactNode } from "react";

/** Page chrome only. The route owns its measure, wording and actions. */
export function PageHeader({ title, eyebrow, meta, actions }: {
  title: string;
  /** A recognition label over the title, such as where a flow stands. */
  eyebrow?: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <section className="page-hero">
      <div>
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        {meta}
      </div>
      {actions}
    </section>
  );
}
