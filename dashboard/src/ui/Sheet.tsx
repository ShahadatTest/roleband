import { ReactNode } from "react";
import { Overlay } from "./Overlay";
import "./Sheet.css";

// Modal, edge-docked overlay shell (drawer). Right-docked by default.

export interface SheetProps {
  isOpen: boolean;
  onClose: () => void;
  children: ReactNode;
  label: string;
  /** Which viewport edge the sheet docks to. Default "right". */
  side?: "right" | "left" | "bottom";
  className?: string;
}

export function Sheet({ isOpen, onClose, children, label, side = "right", className }: SheetProps) {
  return (
    <Overlay
      isOpen={isOpen}
      onClose={onClose}
      label={label}
      modal
      scrim
      wrapperClassName="ui-sheet-wrap"
      className={`ui-sheet ui-sheet-${side}${className ? ` ${className}` : ""}`}
    >
      {children}
    </Overlay>
  );
}
