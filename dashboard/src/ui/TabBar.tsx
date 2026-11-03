import { Fragment, KeyboardEvent, ReactNode, useEffect, useRef } from "react";
import "./TabBar.css";
import { CountBadge } from "./CountBadge";

/* THE tab bar: a row of views of one screen, exactly one current.
 * docs/ui.md
 *
 * One primitive for Settings, Statistics and Review, so no screen writes its
 * own roving-focus handler and scroll-into-view, and no segmented control
 * does a tab bar's job.
 *
 * Semantics are the WAI tablist pattern: `role="tablist"` on the bar, one
 * `role="tab"` per view with `aria-selected` and a roving tabindex, and
 * Left/Right/Home/End moving the selection. The current tab is announced by
 * `aria-selected` and painted off the same attribute — never a class.
 *
 * Geometry is the control scale's `lg` rank (44 / 18 / radius-md / body):
 * a tab is the screen's largest, least frequent control. The bar scrolls
 * horizontally when it is narrower than its tabs and keeps the current tab
 * in view; it never scrolls the page.
 */
export interface TabBarItem<T extends string> {
  id: T;
  label: ReactNode;
  /** A count or status beside the label, in the data voice. */
  badge?: ReactNode;
  disabled?: boolean;
  /** Why a disabled tab is disabled, as its tooltip. */
  title?: string;
  /** id of text on screen that describes the tab, such as why it is locked. */
  describedBy?: string;
  /** This tab starts a new group: a thin rule sets it apart from the tabs
      before it (Profile's walk: Required | Optional | Summary). */
  groupStart?: boolean;
}

export interface TabBarProps<T extends string> {
  /** Accessible name of the bar — which screen's views these are. */
  label: string;
  value: T;
  onChange: (id: T) => void;
  tabs: readonly TabBarItem<T>[];
  /** Element ids are `${idPrefix}-tab-${id}`, for the panel's aria-labelledby. */
  idPrefix: string;
  /** id of the tabpanel every tab controls, when there is one. */
  controls?: string;
  className?: string;
}

export function TabBar<T extends string>({ label, value, onChange, tabs, idPrefix, controls, className }: TabBarProps<T>) {
  const barRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Horizontal only. scrollIntoView would also scroll the page container
    // vertically, hiding the screen's h1 on a deep link.
    const bar = barRef.current;
    const button = bar?.querySelector<HTMLElement>(`#${idPrefix}-tab-${value}`);
    if (!bar || !button || typeof bar.scrollTo !== "function") return;
    const offset = button.getBoundingClientRect().left - bar.getBoundingClientRect().left;
    const target = bar.scrollLeft + offset - (bar.clientWidth - button.offsetWidth) / 2;
    bar.scrollTo({ left: Math.max(0, target) });
  }, [idPrefix, value]);

  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const enabled = tabs.filter((t) => !t.disabled);
    const current = enabled.findIndex((t) => t.id === value);
    const next =
      event.key === "Home"
        ? 0
        : event.key === "End"
          ? enabled.length - 1
          : (current + (event.key === "ArrowRight" ? 1 : -1) + enabled.length) % enabled.length;
    const target = enabled[next];
    if (!target) return;
    onChange(target.id);
    barRef.current?.querySelector<HTMLElement>(`#${idPrefix}-tab-${target.id}`)?.focus();
  };

  return (
    <div
      ref={barRef}
      className={`ui-tabbar${className ? ` ${className}` : ""}`}
      role="tablist"
      aria-label={label}
      onKeyDown={onKeyDown}
    >
      {tabs.map((tab, index) => {
        const selected = tab.id === value;
        return (
          <Fragment key={tab.id}>
            {tab.groupStart && index > 0 && <span className="ui-tabbar-rule" aria-hidden="true" />}
            <button
              type="button"
              id={`${idPrefix}-tab-${tab.id}`}
              className="ui-tab"
              role="tab"
              aria-selected={selected}
              aria-controls={controls}
              tabIndex={selected ? 0 : -1}
              disabled={tab.disabled}
              title={tab.title}
              aria-describedby={tab.describedBy}
              onClick={() => {
                if (!selected) onChange(tab.id);
              }}
            >
              {tab.label}
              {/* The space keeps the badge a separate word in the accessible name:
                  "Decision history 9", not "Decision history9". */}
              {tab.badge != null && (
                <>
                  {" "}
                  <CountBadge className="ui-tabbar-badge" spoken>{tab.badge}</CountBadge>
                </>
              )}
            </button>
          </Fragment>
        );
      })}
    </div>
  );
}
