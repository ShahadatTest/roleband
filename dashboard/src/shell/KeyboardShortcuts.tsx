import { Button, Icon, Kbd, Sheet } from "../ui";
import "./KeyboardShortcuts.css";
import {
  shortcutsKeyboardShortcutsAddToCompareOrTake,
  shortcutsKeyboardShortcutsAnywhere,
  shortcutsKeyboardShortcutsClose,
  shortcutsKeyboardShortcutsCloseWhatIsOnTop,
  shortcutsKeyboardShortcutsCtrlK,
  shortcutsKeyboardShortcutsDifferentRoles,
  shortcutsKeyboardShortcutsKeyboardShortcuts,
  shortcutsKeyboardShortcutsKeyboardShortcuts2,
  shortcutsKeyboardShortcutsNextRole,
  shortcutsKeyboardShortcutsOnARoleInA,
  shortcutsKeyboardShortcutsOpenTheCommandPalette,
  shortcutsKeyboardShortcutsOpenTheRole,
  shortcutsKeyboardShortcutsPossibleDuplicates,
  shortcutsKeyboardShortcutsPreviousRole,
  shortcutsKeyboardShortcutsRelatedRoles,
  shortcutsKeyboardShortcutsSameRole,
  shortcutsKeyboardShortcutsSaveItOrUnsaveIt,
  shortcutsKeyboardShortcutsSearchRoles,
  shortcutsKeyboardShortcutsShowTheseShortcuts,
} from "../copy/gen/shortcuts";

/* Every key the app answers to, in one sheet (docs/ui.md "Keys"), so `j`/`k`,
 * `s` and `c` on the radar are said somewhere. Opened by `?`
 * anywhere outside a text field, and by name from the command palette.
 *
 * The shell loads this lazily on first open, so the list costs the startup
 * chunk nothing. The keys themselves are answered where they act — App (the
 * palette, `/`, `?`), JobList (`j`/`k`), JobCard (Enter, `s`, `c`),
 * ReviewScreen (D/T/N) — so a key added there belongs here in the same change.
 */

interface Shortcut {
  keys: string[];
  does: string;
}

const GROUPS: Array<{ title: string; shortcuts: Shortcut[] }> = [
  {
    get title() { return shortcutsKeyboardShortcutsAnywhere(); },
    shortcuts: [
      { get keys() { return ["⌘ K", shortcutsKeyboardShortcutsCtrlK()]; }, get does() { return shortcutsKeyboardShortcutsOpenTheCommandPalette(); } },
      { keys: ["/"], get does() { return shortcutsKeyboardShortcutsSearchRoles(); } },
      { keys: ["?"], get does() { return shortcutsKeyboardShortcutsShowTheseShortcuts(); } },
      { keys: ["esc"], get does() { return shortcutsKeyboardShortcutsCloseWhatIsOnTop(); } },
    ],
  },
  {
    get title() { return shortcutsKeyboardShortcutsOnARoleInA(); },
    shortcuts: [
      { keys: ["j", "↓"], get does() { return shortcutsKeyboardShortcutsNextRole(); } },
      { keys: ["k", "↑"], get does() { return shortcutsKeyboardShortcutsPreviousRole(); } },
      { keys: ["↵"], get does() { return shortcutsKeyboardShortcutsOpenTheRole(); } },
      { keys: ["s"], get does() { return shortcutsKeyboardShortcutsSaveItOrUnsaveIt(); } },
      { keys: ["c"], get does() { return shortcutsKeyboardShortcutsAddToCompareOrTake(); } },
    ],
  },
  {
    // Worded as Review's own console labels its three answers.
    get title() { return shortcutsKeyboardShortcutsPossibleDuplicates(); },
    shortcuts: [
      { keys: ["D"], get does() { return shortcutsKeyboardShortcutsSameRole(); } },
      { keys: ["T"], get does() { return shortcutsKeyboardShortcutsRelatedRoles(); } },
      { keys: ["N"], get does() { return shortcutsKeyboardShortcutsDifferentRoles(); } },
    ],
  },
];

export function KeyboardShortcuts({ onClose }: { onClose: () => void }) {
  return (
    <Sheet isOpen onClose={onClose} label={shortcutsKeyboardShortcutsKeyboardShortcuts2()} className="shortcuts-sheet app-overlay">
      <div className="shortcuts-head">
        <h2>{shortcutsKeyboardShortcutsKeyboardShortcuts()}</h2>
        <Button variant="icon" size="sm" aria-label={shortcutsKeyboardShortcutsClose()} onClick={onClose}>
          <Icon name="close" size={16} />
        </Button>
      </div>
      {GROUPS.map((group) => (
        <section key={group.title} className="shortcuts-group">
          <h3>{group.title}</h3>
          <dl className="shortcuts-list">
            {group.shortcuts.map(({ keys, does }) => (
              <div key={does} className="shortcuts-row">
                <dt>
                  {keys.map((key) => (
                    <Kbd key={key}>{key}</Kbd>
                  ))}
                </dt>
                <dd>{does}</dd>
              </div>
            ))}
          </dl>
        </section>
      ))}
    </Sheet>
  );
}
