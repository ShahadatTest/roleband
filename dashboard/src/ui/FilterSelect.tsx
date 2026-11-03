import { ReactNode, useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { SearchField } from "./SearchField";
import { Button } from "./Button";
import { Icon } from "./Icon";
import { Popover } from "./Popover";
import "./FilterSelect.css";
import {
  sharedFilterRailNoOptionsMatch,
  sharedFilterSelectClear,
  sharedFilterSelectFilter,
  sharedFilterSelectFilterBy,
  sharedFilterSelectOptions,
  sharedFilterSelectSearch,
  sharedFilterSelectSearch2,
} from "../copy/gen/shared";

// Config-driven select-in-a-popover (F1 primitive). One facet = one trigger
// button that opens an option list: single or multi select, optional search,
// optional custom option rendering.
//
// Keyboard: focus stays on one element while the arrows move the active
// option, which that element names in `aria-activedescendant`. Searchable, it
// is the search box, a combobox controlling the list (the command palette's
// pattern); otherwise the list itself, focused when it opens. Options are not
// tab stops.

export interface FilterSelectOption {
  value: string;
  label: string;
  /** Optional count rendered right-aligned (facet cardinality). */
  count?: number;
}

export interface FilterSelectProps {
  /** Facet name shown on the trigger, e.g. "Company". */
  label: string;
  options: FilterSelectOption[];
  selected: string[];
  onChange: (next: string[]) => void;
  /** Multi select (checkbox semantics). Default true; false = single select. */
  multiple?: boolean;
  searchable?: boolean;
  renderOption?: (option: FilterSelectOption, isSelected: boolean) => ReactNode;
  icon?: ReactNode;
  emptyText?: string;
  className?: string;
}

export function FilterSelect({
  label,
  options,
  selected,
  onChange,
  multiple = true,
  searchable = false,
  renderOption,
  icon,
  emptyText = sharedFilterRailNoOptionsMatch(),
  className,
}: FilterSelectProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const id = useId();
  const listId = `${id}-list`;
  // The list holds focus when there is no search box. A callback ref runs
  // before the overlay's own focus effect, which then leaves it there.
  const focusList = useCallback(
    (list: HTMLDivElement | null) => {
      if (list && !searchable) list.focus();
    },
    [searchable],
  );

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return options;
    return options.filter(
      (o) => o.label.toLowerCase().includes(q) || o.value.toLowerCase().includes(q),
    );
  }, [options, query]);

  // Keep the active row valid as the query narrows the list.
  useEffect(() => {
    setActive((a) => Math.max(0, Math.min(a, visible.length - 1)));
  }, [visible.length]);

  const close = () => {
    setOpen(false);
    setQuery("");
    setActive(0);
  };

  const toggleValue = (value: string) => {
    if (!multiple) {
      onChange(selected.includes(value) ? [] : [value]);
      close();
      return;
    }
    onChange(
      selected.includes(value) ? selected.filter((v) => v !== value) : [...selected, value],
    );
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(a + 1, visible.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Home") {
      e.preventDefault();
      setActive(0);
    } else if (e.key === "End") {
      e.preventDefault();
      setActive(Math.max(0, visible.length - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const option = visible[active];
      if (option) toggleValue(option.value);
    }
  };

  const triggerText = selected.length === 0 ? label : `${label} · ${selected.length}`;
  const activeId = visible.length ? `${id}-opt-${active}` : undefined;

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className={`ui-filterselect-trigger${open ? " ui-open" : ""}${
          selected.length ? " ui-has-value" : ""
        }${className ? ` ${className}` : ""}`}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={sharedFilterSelectFilterBy({ label: String(label.toLowerCase()) })}
        onClick={() => (open ? close() : setOpen(true))}
      >
        {icon}
        {triggerText}
      </button>
      <Popover
        isOpen={open}
        onClose={close}
        anchor={triggerRef.current}
        label={sharedFilterSelectFilter({ label: String(label) })}
        className="ui-filterselect-pop"
      >
        <div className="ui-filterselect" onKeyDown={onKeyDown}>
          <div className="ui-filterselect-head">
            <strong>{label}</strong>
            {multiple && selected.length > 0 && (
              <Button variant="link" className="ui-btn-quiet" onClick={() => onChange([])}>
                {sharedFilterSelectClear()}
              </Button>
            )}
          </div>
          {searchable && (
            <SearchField
              size="sm"
              className="ui-filterselect-search"
              autoFocus
              label={sharedFilterSelectSearch({ label: String(label.toLowerCase()) })}
              placeholder={sharedFilterSelectSearch2({ label: String(label.toLowerCase()) })}
              value={query}
              onChange={setQuery}
              role="combobox"
              aria-expanded
              aria-controls={listId}
              aria-autocomplete="list"
              aria-activedescendant={activeId}
            />
          )}
          <div
            ref={focusList}
            id={listId}
            className="ui-filterselect-list"
            role="listbox"
            aria-label={sharedFilterSelectOptions({ label: String(label) })}
            aria-multiselectable={multiple || undefined}
            aria-activedescendant={searchable ? undefined : activeId}
            tabIndex={searchable ? undefined : 0}
          >
            {visible.length === 0 && <div className="ui-filterselect-empty">{emptyText}</div>}
            {visible.map((option, i) => {
              const isSelected = selected.includes(option.value);
              return (
                <button
                  key={option.value}
                  type="button"
                  id={`${id}-opt-${i}`}
                  role="option"
                  tabIndex={-1}
                  aria-selected={isSelected}
                  className={`ui-filterselect-option${i === active ? " ui-cursor" : ""}`}
                  onClick={() => toggleValue(option.value)}
                  onMouseEnter={() => setActive(i)}
                >
                  {renderOption ? (
                    renderOption(option, isSelected)
                  ) : (
                    <>
                      <span className="ui-filterselect-mark" aria-hidden="true">
                        {isSelected && <Icon name="check" size={12} />}
                      </span>
                      <span className="ui-filterselect-label">{option.label}</span>
                      {option.count != null && (
                        <span className="ui-filterselect-count">{option.count}</span>
                      )}
                    </>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      </Popover>
    </>
  );
}
