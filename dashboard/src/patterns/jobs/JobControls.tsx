import {
  jobsSave,
  jobsSaveTitle,
  jobsSaved,
  jobsSavedTitle,
} from "../../copy/gen/jobs";
import { Button, Icon } from "../../ui";

// Controls that ACT on a job. Read-only chips are ./JobBadges.
export function StarButton({
  on,
  onToggle,
  size = 18,
  shortcut,
}: {
  on: boolean;
  onToggle: () => void;
  size?: number;
  /** The key that does the same on the surface around this star, named in its
   *  tooltip. Only where a key really does it: a job row answers `s`, a
   *  comparison column does not. */
  shortcut?: string;
}) {
  return (
    <Button
      variant="icon"
      size="sm"
      className="star-btn"
      onClick={(e) => {
        e.stopPropagation();
        onToggle();
      }}
      aria-pressed={on}
      aria-label={jobsSave()}
      title={shortcut ? (on ? jobsSavedTitle : jobsSaveTitle)({ key: shortcut }) : on ? jobsSaved() : jobsSave()}
    >
      {/* `filled`: the saved state reads as a solid star, unsaved as an
          outline. */}
      <Icon name="star" size={size} filled={on} />
    </Button>
  );
}
