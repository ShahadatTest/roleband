import {
  shellPaletteActions,
  shellPaletteAria,
  shellPaletteClearCompare,
  shellPaletteCompare,
  shellPaletteEmpty,
  shellPaletteListAria,
  shellPaletteHintClose,
  shellPaletteHintNavigate,
  shellPaletteHintSelect,
  shellPaletteNavigate,
  shellPalettePlaceholder,
  shellPaletteQueryAria,
  shellPaletteSearch,
  shellPaletteShortcuts,
  shellPaletteSubtab,
  shellPaletteThemeDark,
  shellPaletteThemeLight,
} from "../copy/gen/shell";
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { NAV_TABS } from "../navigation";
import { useJobActions, useJobWorkspace } from "../context/JobWorkspace";
import { useMissionActions } from "../context/MissionState";
import { useClearCompare } from "../patterns/compare/useClearCompare";
import { Icon, type IconName } from "../ui/Icon";
import { Kbd } from "../ui/Kbd";
import { Overlay } from "../ui/Overlay";

interface Command {
  id: string;
  /** The group caption, from the catalog: commands of one group share it. */
  section: string;
  label: string;
  icon: IconName;
  hint?: string;
  run: () => void;
}

/**
 * Where the selected command sits in the list as it stands NOW.
 *
 * The selection identifies a command, never a position: `items` is re-derived
 * on every render, and `items[0]` is the free-text role search whenever the
 * query is non-empty. With an index, a keystroke whose state commit lands
 * after an ArrowDown re-numbers the list under the selection, so Enter runs
 * the search command and navigates to "/" instead of the row the user can see
 * highlighted.
 *
 * A selection the newest query filtered out falls back to the top result, which
 * keeps the invariant that matters: what Enter runs is what is highlighted.
 */
function selectedIndex(items: Command[], id: string | null): number {
  const at = items.findIndex((c) => c.id === id);
  return at === -1 && items.length > 0 ? 0 : at;
}

export function CommandPalette({
  open,
  onClose,
  theme,
  onToggleTheme,
  onShowShortcuts,
}: {
  open: boolean;
  onClose: () => void;
  theme: string;
  onToggleTheme: () => void;
  /** Opens the keyboard shortcuts sheet, which the shell owns. */
  onShowShortcuts?: () => void;
}) {
  const navigate = useNavigate();
  const { setSearch } = useMissionActions();
  const { compareIds } = useJobWorkspace();
  const { openCompare } = useJobActions();
  // The comparison's own recipe, Undo included.
  const clearCompare = useClearCompare();
  const [query, setQuery] = useState("");
  const [selId, setSelIdState] = useState<string | null>(null);
  // Selection is mirrored in a ref so fast ArrowDown→Enter sequences act on
  // the just-moved selection instead of a stale render closure.
  const selIdRef = useRef<string | null>(null);
  const setSel = (id: string | null) => {
    selIdRef.current = id;
    setSelIdState(id);
  };
  const inputRef = useRef<HTMLInputElement | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  /* Where the pointer was last seen over the list. A row takes the highlight
     only when the pointer has MOVED: arrowing scrolls rows under a still
     pointer, and the browser reports that as the pointer entering them, which
     would pull the highlight back under the mouse and make Enter run a row
     the keyboard never reached. Null until the pointer is first seen, so a
     palette that opens under a resting pointer keeps its first row. */
  const pointerAt = useRef<{ x: number; y: number } | null>(null);
  const pointerMoved = (e: { clientX: number; clientY: number }) => {
    const last = pointerAt.current;
    pointerAt.current = { x: e.clientX, y: e.clientY };
    return last !== null && (last.x !== e.clientX || last.y !== e.clientY);
  };

  const commands = useMemo<Command[]>(() => {
    const nav: Command[] = NAV_TABS.flatMap((t) => {
      const top: Command = {
        id: `nav:${t.path}`,
        section: shellPaletteNavigate(),
        label: t.label,
        icon: t.icon,
        run: () => navigate(t.path),
      };
      // Multi-tab sections also expose each sub-tab as a direct jump, so the
      // palette can deep-link to e.g. "Statistics: Velocity".
      const subs: Command[] = (t.tabs ?? []).map((sub) => ({
        id: `nav:${t.path}/${sub.slug}`,
        section: shellPaletteNavigate(),
        label: shellPaletteSubtab({ section: t.label, tab: sub.label }),
        icon: t.icon,
        run: () => navigate(`${t.path}/${sub.slug}`),
      }));
      return [top, ...subs];
    });
    const actions: Command[] = [
      {
        id: "theme",
        section: shellPaletteActions(),
        label: theme === "dark" ? shellPaletteThemeLight() : shellPaletteThemeDark(),
        icon: theme === "dark" ? "sun" : "moon",
        run: onToggleTheme,
      },
    ];
    if (onShowShortcuts) {
      actions.push({
        id: "shortcuts",
        section: shellPaletteActions(),
        label: shellPaletteShortcuts(),
        icon: "help",
        hint: "?",
        run: onShowShortcuts,
      });
    }
    // Compare is a cover, not a place, so it is not in NAV_TABS: from two
    // roles the palette offers the comparison itself.
    if (compareIds.size >= 2) {
      actions.push({
        id: "open-compare",
        section: shellPaletteActions(),
        label: shellPaletteCompare({ count: compareIds.size }),
        icon: "columns",
        run: openCompare,
      });
    }
    if (compareIds.size > 0) {
      actions.push({
        id: "clear-compare",
        section: shellPaletteActions(),
        label: shellPaletteClearCompare({ count: compareIds.size }),
        icon: "columns",
        run: clearCompare,
      });
    }
    return [...nav, ...actions];
  }, [navigate, theme, onToggleTheme, onShowShortcuts, compareIds, clearCompare, openCompare]);

  const q = query.trim().toLowerCase();
  const matches = q ? commands.filter((c) => c.label.toLowerCase().includes(q)) : commands;
  // Free text always offers a role search as the first result.
  const searchItem: Command | null = q
    ? {
        id: "search",
        section: shellPaletteActions(),
        label: shellPaletteSearch({ query: query.trim() }),
        icon: "search",
        hint: "↵",
        run: () => {
          setSearch(query.trim());
          navigate("/");
        },
      }
    : null;
  const items = searchItem ? [searchItem, ...matches] : matches;
  const sel = selectedIndex(items, selId);

  useEffect(() => {
    if (open) {
      setQuery("");
      setSel(null);
      pointerAt.current = null;
    }
  }, [open]);

  // Callback ref: focuses the instant the input mounts, which is more reliable
  // than a rAF scheduled from the open effect. STABLE identity, so it runs on
  // mount and unmount only: React re-runs a callback ref whose identity changes,
  // and an inline one changes on every render, so any re-render while open (the
  // compare selection hydrating, say) would pull focus back to the input and
  // re-capture the opener as whatever held focus then.
  const focusOnMount = useCallback((el: HTMLInputElement | null) => {
    inputRef.current = el;
    if (!el) return;
    /* Capture the opener HERE, not in an effect. This callback runs during
       commit and effects run after it, so by then the previous element is this
       input and "restore" would put focus back where it already is. */
    // A ref reattachment while this input is focused keeps the original opener.
    if (document.activeElement !== el) {
      restoreRef.current =
        document.activeElement instanceof HTMLElement ? document.activeElement : null;
    }
    el.focus();
  }, []);

  useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>(`[data-idx="${sel}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [sel]);

  // Arrows walk from the highlighted row; falling off either end is a no-op,
  // which leaves the selection where it already is.
  const move = (delta: number) => {
    const next = items[selectedIndex(items, selIdRef.current) + delta];
    if (next) setSel(next.id);
  };

  const run = (c: Command) => {
    onClose();
    c.run();
  };

  /* Focus goes back where it came from. Dropped on <body>, a keyboard user who
     hit Cmd-K and changed their mind would lose their place in the page
     entirely and have to tab in from the top. */
  const restoreRef = useRef<HTMLElement | null>(null);
  useEffect(() => {
    if (!open) return;
    return () => {
      const restore = restoreRef.current;
      if (restore && document.contains(restore)) restore.focus();
    };
  }, [open]);

  /* Escape is the one key that is not the palette's alone: it closes the
     topmost surface, and only that one. ui/Overlay puts the palette
     on that stack; opened last, it is the top of it. */

  // The other keys are handled at the window while open, so the palette keeps
  // working even if focus escapes the input (modal behavior, not focus-dependent).
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        move(1);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        move(-1);
      } else if (e.key === "Enter") {
        e.preventDefault();
        const item = items[selectedIndex(items, selIdRef.current)];
        if (item) run(item);
      } else if (
        document.activeElement !== inputRef.current &&
        e.key.length === 1 &&
        !e.metaKey && !e.ctrlKey && !e.altKey
      ) {
        // Stray printable keystroke while the input lost focus: reclaim it.
        inputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  });

  if (!open) return null;

  let lastSection: string | null = null;
  /* Command ids are route paths ("nav:/favorites"), which are legal in an HTML
     id and unusable in a CSS selector. aria-activedescendant is resolved by id,
     so both ends use this same sanitized form. */
  const optionDomId = (id: string) => `palette-opt-${id.replace(/[^\w-]/g, "_")}`;

  return (
    /* ui/Overlay holds the keyboard and the page: an aria-modal="true" that
       traps nothing lets Tab reach the page behind it and the page scroll
       underneath. It keeps its OWN focus capture and restore
       (takeFocus={false}): the opener is captured in the input's callback ref,
       which runs before any effect, so by Overlay's effect the active element
       is already the input and Overlay's restore would aim there. */
    <Overlay
      isOpen
      onClose={onClose}
      label={shellPaletteAria()}
      takeFocus={false}
      wrapperClassName="palette-wrap"
      className="palette"
    >
      {/* A LABEL, not a div with a focus handler: clicking anywhere in the
          field focuses its input because that is what a label does.
          The visible name lives on the input's aria-label; this
          wrapper is the hit area. */}
      <label className="palette-input">
        <Icon name="search" size={16} />
        {/* The highlighted row is announced through the INPUT, which is where
            focus stays: a purely visual class would leave a screen-reader user
            hearing nothing on ArrowDown, not knowing what Enter would run. */}
        <input
          ref={focusOnMount}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={shellPalettePlaceholder()}
          aria-label={shellPaletteQueryAria()}
          role="combobox"
          aria-expanded
          aria-controls="palette-list"
          aria-autocomplete="list"
          aria-activedescendant={items[sel] ? optionDomId(items[sel].id) : undefined}
        />
        <Kbd>esc</Kbd>
      </label>
      {/* A listbox owns its options DIRECTLY: a generic wrapper between the
          listbox and an option breaks the ownership the pattern requires, and
          a listbox may hold only options. Fragments carry the key, and the
          captions are presentational. */}
      <div className="palette-list" id="palette-list" ref={listRef} role="listbox" aria-label={shellPaletteListAria()}>
        {items.length === 0 && <div className="palette-empty">{shellPaletteEmpty()}</div>}
        {items.map((c, i) => {
          const header = c.section !== lastSection ? c.section : null;
          lastSection = c.section;
          return (
            <Fragment key={c.id}>
              {header && !q && (
                <div className="palette-section" role="presentation">{header}</div>
              )}
              <button
                id={optionDomId(c.id)}
                data-idx={i}
                role="option"
                aria-selected={i === sel}
                className={`palette-item${i === sel ? " is-cursor" : ""}`}
                onMouseMove={(e) => {
                  if (pointerMoved(e) && selIdRef.current !== c.id) setSel(c.id);
                }}
                onClick={() => run(c)}
              >
                <Icon name={c.icon} size={15} />
                <span className="grow">{c.label}</span>
                {c.hint && <span className="hint">{c.hint}</span>}
              </button>
            </Fragment>
          );
        })}
      </div>
      <div className="palette-foot">
        <span><Kbd>↑</Kbd><Kbd>↓</Kbd> {shellPaletteHintNavigate()}</span>
        <span><Kbd>↵</Kbd> {shellPaletteHintSelect()}</span>
        <span><Kbd>esc</Kbd> {shellPaletteHintClose()}</span>
      </div>
    </Overlay>
  );
}
