import { notificationText } from "../../api/notificationText";
import { Content } from "../../ui/Content";

/* A notification's words in the bell's panel, said from the catalog
 * with third-party text marked. Its own module so the bell, which
 * the shell imports, loads it only when the panel opens. */
export function BellText({ n }: { n: { title: string; body?: string | null; meta?: Record<string, unknown> | null } }) {
  const text = notificationText(n);
  return (
    <>
      <strong>{text.title}</strong>
      {text.body && <span>{text.bodyIsContent ? <Content text={text.body} /> : text.body}</span>}
    </>
  );
}
