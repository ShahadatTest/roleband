/* The copy review deck (dev only, `/__copy-review/`; docs/copy.md).
 * Every English message with its contract, uses and diagnostics, and per
 * language its state and samples beside the English. The data comes from
 * `scripts/copy/review.mjs` through the Vite plugin's worker. */
import { useEffect, useState } from "react";
import { Button, SearchField, Select } from "../../ui";
import * as M from "../gen/review";
import { number } from "../format";

interface Variant {
  args: Record<string, string | number>;
  english: string;
  text: string;
}
/** One message in one language. */
interface Words {
  status: string;
  editorial: string;
  origin: string;
  source: string | null;
  variants: Variant[];
}
interface Message {
  id: string;
  kind: string;
  file: string;
  line: number;
  source: string;
  selectors: unknown;
  rules: string[];
  parameters: string[];
  terms: string[];
  meta: Record<string, string>;
  uses: { file: string; line: number; mode: string }[];
  locales: Record<string, Words>;
  diagnostics: string[];
}
interface Data {
  locales: { code: string; name: string }[];
  messages: Message[];
  changed: string[];
}
interface Filters {
  query: string;
  locale: string;
  kind: string;
  status: string;
  surface: string;
  rule: string;
  changes: string;
}

declare const __COPY_SOURCE_ROOT__: string;

const PAGE = 50;

/** A translation state or an editorial state, said at render. */
const labels: Record<string, () => string> = {
  source: M.reviewSource,
  current: M.reviewCurrent,
  stale: M.reviewStale,
  missing: M.reviewMissing,
  quarantined: M.reviewQuarantined,
  "english-only": M.reviewEnglishOnly,
  unreviewed: M.reviewUnreviewed,
  reviewed: M.reviewReviewed,
  "review-stale": M.reviewReviewStale,
};

/** Opens a source line in the editor. */
const editorLink = (path: string, line: number) => `vscode://file/${encodeURI(path)}:${line}`;

const distinct = (values: string[]) => [...new Set(values)].sort();

function matches(m: Message, f: Filters, changed: string[]): boolean {
  const own = m.locales[f.locale];
  return (
    (!f.surface || m.file === f.surface) &&
    (!f.rule || m.rules.includes(f.rule)) &&
    (!f.changes || changed.includes(m.id)) &&
    (!f.kind || m.kind === f.kind) &&
    (!f.status || [own?.status, own?.editorial].includes(f.status)) &&
    JSON.stringify(m).toLowerCase().includes(f.query.toLowerCase())
  );
}

/** The deck's data, or `failed` when the dev server could not build it. */
function useDeckData(): { data: Data | null; failed: boolean } {
  const [data, setData] = useState<Data | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let alive = true;
    void fetch("/__copy-review/data")
      .then((response) => {
        if (!response.ok) throw new Error(String(response.status));
        return response.json();
      })
      .then(
        (loaded) => {
          if (alive) setData(loaded);
        },
        () => {
          if (alive) setFailed(true);
        },
      );
    return () => {
      alive = false;
    };
  }, []);
  return { data, failed };
}

/** A rendered sample, flagged when it overflows the message's declared width. */
function Sample({ text, width }: { text: string; width?: string }) {
  const [overflow, setOverflow] = useState(false);
  return (
    <div className="review-sample">
      <span
        style={{ maxWidth: width }}
        ref={(el) => {
          if (el) setOverflow(el.scrollWidth > el.clientWidth);
        }}
      >
        {text}
      </span>
      {overflow && <small>{M.reviewWidth()}</small>}
    </div>
  );
}

function Controls({ data, filters, set }: { data: Data | null; filters: Filters; set: (change: Partial<Filters>) => void }) {
  const messages = data?.messages ?? [];
  const all = { value: "", label: M.reviewAll() };
  const options = (values: string[]) => [all, ...values.map((value) => ({ value, label: value }))];
  return (
    <div className="review-controls">
      <SearchField disabled={!data} label={M.reviewSearch()} value={filters.query} onChange={(query) => set({ query })} />
      <Select
        disabled={!data}
        label={M.reviewLanguage()}
        value={filters.locale}
        onChange={(locale) => set({ locale })}
        options={(data?.locales ?? []).map((l) => ({ value: l.code, label: l.name }))}
      />
      <Select
        disabled={!data}
        label={M.reviewKind()}
        value={filters.kind}
        onChange={(kind) => set({ kind })}
        options={options(distinct(messages.map((m) => m.kind)))}
      />
      <Select
        disabled={!data}
        label={M.reviewStatus()}
        value={filters.status}
        onChange={(status) => set({ status })}
        options={[all, ...Object.entries(labels).map(([value, label]) => ({ value, label: label() }))]}
      />
      <Select
        disabled={!data}
        label={M.reviewSurface()}
        value={filters.surface}
        onChange={(surface) => set({ surface })}
        options={options(distinct(messages.map((m) => m.file)))}
      />
      <Select
        disabled={!data}
        label={M.reviewRule()}
        value={filters.rule}
        onChange={(rule) => set({ rule })}
        options={options(distinct(messages.flatMap((m) => m.rules)))}
      />
      <Select
        disabled={!data}
        label={M.reviewChanges()}
        value={filters.changes}
        onChange={(changes) => set({ changes })}
        options={[all, { value: "changed", label: M.reviewChanged() }]}
      />
    </div>
  );
}

/** One message: its states in the chosen language, source and contract, uses,
    each sample beside the English, and its diagnostics. */
function MessageCard({ m, locale }: { m: Message; locale: string }) {
  const own = m.locales[locale];
  return (
    <article id={m.id}>
      <header>
        <h2>{m.id}</h2>
        <span>{m.kind} · {labels[own.status]?.()} · {labels[own.editorial]?.()}</span>
      </header>
      <a href={editorLink(`${__COPY_SOURCE_ROOT__}/${m.file}`, m.line)}>{m.file}:{m.line}</a>
      <p>{M.reviewRendered({ language: own.origin })}</p>
      <details>
        <summary>{M.reviewContract()}</summary>
        <pre>{m.source}</pre>
        <pre>{own.source}</pre>
        <pre>{JSON.stringify({ selectors: m.selectors, metadata: m.meta }, null, 2)}</pre>
      </details>
      <dl>
        <dt>{M.reviewParameters()}</dt>
        <dd>{m.parameters.join(", ")}</dd>
        <dt>{M.reviewTerms()}</dt>
        <dd>{m.terms.join(", ")}</dd>
        <dt>{M.reviewUses()}</dt>
        <dd>{number(m.uses.length)}</dd>
      </dl>
      <details>
        <summary>{M.reviewUses()}</summary>
        {m.uses.map((u) => (
          <p key={`${u.file}:${u.line}`}>
            <a href={editorLink(`${__COPY_SOURCE_ROOT__}/../${u.file}`, u.line)}>{u.file}:{u.line}</a> · {u.mode}
          </p>
        ))}
      </details>
      {own.variants.map((v, i) => (
        <div className="review-variant" key={i}>
          <code>{JSON.stringify(v.args)}</code>
          <div className="review-columns">
            <Sample text={v.english} width={m.meta.width} />
            <Sample text={v.text} width={m.meta.width} />
          </div>
        </div>
      ))}
      {m.diagnostics.length > 0 && (
        <details>
          <summary>{M.reviewDiagnostics()} ({number(m.diagnostics.length)})</summary>
          {m.diagnostics.map((d, i) => (
            <p key={i}>{d}</p>
          ))}
        </details>
      )}
    </article>
  );
}

export function Deck() {
  const { data, failed } = useDeckData();
  const [limit, setLimit] = useState(PAGE);
  const [filters, setFilters] = useState<Filters>({ query: "", locale: "es", kind: "", status: "", surface: "", rule: "", changes: "" });
  const set = (change: Partial<Filters>) => setFilters((current) => ({ ...current, ...change }));
  if (failed) return <p role="alert">{M.reviewError()}</p>;

  const rows = data?.messages.filter((m) => matches(m, filters, data.changed)) ?? [];
  return (
    <main className="copy-review" aria-busy={!data}>
      <h1>{M.reviewTitle()}</h1>
      <Controls data={data} filters={filters} set={set} />
      {data && <p>{M.reviewCount({ count: rows.length })}</p>}
      {rows.slice(0, limit).map((m) => (
        <MessageCard key={m.id} m={m} locale={filters.locale} />
      ))}
      {rows.length > limit && <Button onClick={() => setLimit((n) => n + PAGE)}>{M.reviewMore()}</Button>}
    </main>
  );
}
