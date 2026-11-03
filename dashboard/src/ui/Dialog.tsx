import { ReactNode } from "react";
import { Overlay } from "./Overlay";
import "./Dialog.css";

// Modal, centered overlay shell: dim scrim, focus trap, Escape/scrim close.

export interface DialogProps {
  isOpen: boolean;
  onClose: () => void;
  children: ReactNode;
  label: string;
  /** Content width; the dialog never exceeds the viewport. */
  width?: number | string;
  surface?: "glass" | "solid";
  className?: string;
  /** Set false for confirm-style dialogs that must be answered. Default true. */
  closeOnScrim?: boolean;
}

export function Dialog({
  isOpen,
  onClose,
  children,
  label,
  width,
  surface = "glass",
  className,
  closeOnScrim = true,
}: DialogProps) {
  return (
    <Overlay
      isOpen={isOpen}
      onClose={onClose}
      label={label}
      modal
      scrim
      closeOnScrim={closeOnScrim}
      wrapperClassName="ui-dialog-wrap"
      className={`ui-dialog${surface === "solid" ? " ui-dialog-solid" : ""}${className ? ` ${className}` : ""}`}
      style={width != null ? { width } : undefined}
    >
      {children}
    </Overlay>
  );
}
