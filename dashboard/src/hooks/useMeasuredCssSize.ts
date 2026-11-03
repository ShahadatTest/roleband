import { useLayoutEffect, useRef, type RefObject } from "react";

type Binding = {
  root: HTMLElement;
  element: HTMLElement;
  property: string;
  ignoreZero: boolean;
  measure: () => void;
  dispose: () => void;
};

/** Publish a toolbar's height before paint. Render, window resize and container
 * resize are independent signals: none sees every reflow in every host.
 * Ref targets may arrive after loading or be replaced without remounting. */
export function useMeasuredCssSize({ rootRef, elementRef, property, ignoreZero = false }: {
  rootRef: RefObject<HTMLElement | null>;
  elementRef: RefObject<HTMLElement | null>;
  property: `--${string}`;
  /** Register toolbars keep the CSS fallback while hidden/unmeasurable. */
  ignoreZero?: boolean;
}) {
  const binding = useRef<Binding | null>(null);

  useLayoutEffect(() => {
    const root = rootRef.current;
    const element = elementRef.current;
    const previous = binding.current;
    if (previous && (previous.root !== root || previous.element !== element ||
      previous.property !== property || previous.ignoreZero !== ignoreZero)) {
      previous.dispose();
      binding.current = null;
    }
    if (!root || !element) return;

    if (!binding.current) {
      const original = root.style.getPropertyValue(property);
      const priority = root.style.getPropertyPriority(property);
      let written: string | null = null;
      let active = true;
      const measure = () => {
        if (!active) return;
        const height = element.getBoundingClientRect().height;
        if (!Number.isFinite(height) || (ignoreZero && height <= 0)) return;
        const value = `${height}px`;
        if (value === written) return;
        root.style.setProperty(property, value);
        written = value;
      };
      const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
      // Match getBoundingClientRect: padding/border changes count too.
      observer?.observe(element, { box: "border-box" });
      window.addEventListener("resize", measure);
      binding.current = {
        root, element, property, ignoreZero, measure,
        dispose: () => {
          active = false;
          observer?.disconnect();
          window.removeEventListener("resize", measure);
          // Restore only our own write, never a later external owner's value.
          if (written !== null && root.style.getPropertyValue(property) === written) {
            if (original) root.style.setProperty(property, original, priority);
            else root.style.removeProperty(property);
          }
        },
      };
    }
    binding.current.measure();
  });

  useLayoutEffect(() => () => {
    binding.current?.dispose();
    binding.current = null;
  }, []);
}
