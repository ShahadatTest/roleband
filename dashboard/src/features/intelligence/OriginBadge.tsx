import { Icon } from "../../ui";
import {
  aiOriginBadgeCloudConnected,
} from "../../copy/gen/ai";

/** Where a card's capability runs. A label, never a hue. */
export function OriginBadge({ origin, to }: { origin: "local" | "cloud"; to?: string }) {
  return (
    <span className={`intel-origin is-${origin}`}>
      <Icon name={origin === "local" ? "laptop" : "cloud"} size={14} />
      {aiOriginBadgeCloudConnected({ choice: (origin === "local") ? "yes" : "no" })}
      {to && <span className="intel-origin-to">· {to}</span>}
    </span>
  );
}
