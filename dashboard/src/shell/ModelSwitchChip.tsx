import { shellModelSwitch, shellModelSwitchAria, shellModelSwitchTitle } from "../copy/gen/shell";
import { useSyncStatus } from "../context/SyncState";
import { Icon } from "../ui/Icon";
import { StatChip } from "./StatChip";

/* A matching-model download or switch runs for minutes, and its progress lives
 * in Settings > AI. Anywhere else this chip says one is running and is the way
 * back to it; it leaves when the job ends. Read from the status poll the shell
 * already makes, so no screen pays for it. */
export function ModelSwitchChip() {
  const { status } = useSyncStatus();
  const phase = status?.matching_switch ?? "none";
  if (phase === "none") return null;
  return (
    <StatChip
      kind="link"
      to="/settings/intelligence"
      n={<Icon name="sparkle" size={13} />}
      label={shellModelSwitch({ phase })}
      ariaLabel={shellModelSwitchAria({ phase })}
      title={shellModelSwitchTitle()}
    />
  );
}
