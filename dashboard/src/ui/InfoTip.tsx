import "./InfoTip.css";
import { useId } from "react";
import { Icon } from "./Icon";
import { uiInfoTipMoreInformation } from "../copy/gen/ui";

export function InfoTip({
  children,
  label = uiInfoTipMoreInformation(),
}: {
  children: React.ReactNode;
  label?: string;
}) {
  const id = useId();
  return (
    <span className="info-tip">
      <button
        type="button"
        className="info-tip-trigger"
        aria-label={label}
        aria-describedby={id}
      >
        <Icon name="info" size={13} />
      </button>
      <span className="info-tip-popover" id={id} role="tooltip">
        {children}
      </span>
    </span>
  );
}
