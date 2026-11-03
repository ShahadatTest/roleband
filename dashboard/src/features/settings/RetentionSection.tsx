import { number as copyNumber } from "../../copy/format";
import { errorText } from "../../api/errorText";
import { useState } from "react";
import { RetentionState, api } from "../../api";
import { formatWhen } from "../../format";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { Card, CardMessage, CardRow } from "../../ui/Card";
import { AsyncBoundary, Button, Select } from "../../ui";
import type { SelectOption } from "../../ui";
import {
  settingsSaveFailed,
  settingsLoading,
  settingsRetentionSection1Year,
  settingsRetentionSectionAPostingStopsBeingRead,
  settingsCancel,
  settingsRetentionSectionDataRetention,
  settingsRetentionSectionDays,
  settingsRetentionSectionDue,
  settingsRetentionSectionDueCount,
  settingsRetentionSectionDueDetail,
  settingsRetentionSectionDueForRemoval,
  settingsRetentionSectionFromCompaniesYouStoppedFollowing,
  settingsRetentionSectionKept,
  settingsRetentionSectionLastRemoval,
  settingsRetentionSectionLoadFailed,
  settingsRetentionSectionMakesPostingsDueTheyAre,
  settingsRetentionSectionNever,
  settingsRetentionSectionRolebandKeepsEveryPostingIts,
  settingsRetentionSectionNoLongerListed,
  settingsRetentionSectionNoneYet,
  settingsRetentionSectionRemoveAfter,
  settingsRetentionSectionRemovePostingsAfter,
  settingsRetentionSectionRemovePostingsAfter2,
  settingsRetentionSectionRemoved,
  settingsRetentionSectionSaved,
  settingsRetentionSectionText,
} from "../../copy/gen/settings";
import { Msg } from "../../ui/Msg";

// Settings > Data retention. RoleBand keeps every posting its scans
// read, so a wider "what you look for" can put roles on the radar at once.
// A posting no scan has read for the chosen time is removed; roles on the
// radar, saved roles and their history never are. One control: the window.
// A longer window, or Never, saves on change; a shorter one makes postings due,
// so it waits for a confirm that names how many: a pointer slip on the list
// must not make postings due. Nothing is removed by the save
// itself, so a row of its own says what is due and that scans remove it.

const NEVER = "never";

const LABELS: Record<number, string> = { get 365() { return settingsRetentionSection1Year(); } };
const choiceLabel = (days: number) => LABELS[days] ?? settingsRetentionSectionDays({ days: days });

function options(state: RetentionState): SelectOption<string>[] {
  return [
    ...state.choices.map((choice) => ({
      value: String(choice.days),
      // What each choice would remove now: the preview before a change.
      label: choice.due > 0
        ? settingsRetentionSectionDue({ days: String(choiceLabel(choice.days)), due: String(copyNumber(choice.due)) })
        : choiceLabel(choice.days),
    })),
    { value: NEVER, label: settingsRetentionSectionNever() },
  ];
}

const daysOf = (value: string) => (value === NEVER ? null : Number(value));

/** Does `value` remove postings sooner than the saved window? Never is the
 *  longest of all. */
function isShorter(value: string, saved: number | null): boolean {
  const days = daysOf(value);
  return days !== null && (saved === null || days < saved);
}

function confirmLine(state: RetentionState, value: string): string {
  const days = Number(value);
  const due = state.choices.find((choice) => choice.days === days)?.due ?? 0;
  return settingsRetentionSectionMakesPostingsDueTheyAre({ days: String(choiceLabel(days)), due: String(copyNumber(due)) });
}

const dueCount = (state: RetentionState) =>
  settingsRetentionSectionDueCount({ count: state.due, due: String(copyNumber(state.due)) });

function lastRemoval(state: RetentionState): string {
  const last = state.last_removed;
  if (!last) return settingsRetentionSectionNoneYet();
  const more = settingsRetentionSectionText({ choice: (last.more) ? "yes" : "no" });
  return settingsRetentionSectionRemoved({ at: String(formatWhen(last.at)), removed: String(copyNumber(last.removed)), more: String(more) });
}

export function RetentionSection() {
  const retention = useAsyncResource<RetentionState>(() => api.retention(), []);
  const { mutate } = retention;
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** A shorter window chosen and not yet confirmed. */
  const [pending, setPending] = useState<string | null>(null);

  const save = async (value: string) => {
    setPending(null);
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      const next = await api.saveRetention({ days: daysOf(value) });
      mutate(() => next);
      setSaved(true);
    } catch (caught) {
      // The Select is controlled by the saved state, so it returns to the
      // saved value on its own.
      setError(errorText(caught, settingsSaveFailed()));
    } finally {
      setSaving(false);
    }
  };

  const choose = (value: string, saved: number | null) => {
    if (isShorter(value, saved)) {
      setSaved(false);
      setError(null);
      setPending(value);
      return;
    }
    void save(value);
  };

  return (
    <Card
      title={settingsRetentionSectionDataRetention()}
      intro={settingsRetentionSectionRolebandKeepsEveryPostingIts()}
    >
      <AsyncBoundary
        resource={retention}
        failed={settingsRetentionSectionLoadFailed()}
        skeleton={<CardRow title={settingsRetentionSectionRemovePostingsAfter()} facts={settingsLoading()} />}
      >
        {(state) => (
          <>
            <CardRow
              title={settingsRetentionSectionRemovePostingsAfter()}
              description={
                settingsRetentionSectionAPostingStopsBeingRead()
              }
              facts={
                <span data-testid="retention-counts">
                  <Msg of={settingsRetentionSectionKept} elems={{ stored: copyNumber(state.stored) }} />
                  {(" " + settingsRetentionSectionNoLongerListed({ no_longer_listed: String(copyNumber(state.no_longer_listed)) }))}
                  {(" " + settingsRetentionSectionFromCompaniesYouStoppedFollowing({ stopped_following: String(copyNumber(state.stopped_following)) }))}
                </span>
              }
              trailing={
                <Select
                  label={settingsRetentionSectionRemovePostingsAfter2()}
                  value={pending ?? (state.days === null ? NEVER : String(state.days))}
                  onChange={(value) => choose(value, state.days)}
                  options={options(state)}
                  disabled={saving}
                />
              }
            />
            {pending !== null && (
              <CardMessage tone="danger" role="note">
                <span data-testid="retention-confirm">{confirmLine(state, pending)}</span>
                <span className="settings-message-actions">
                  <Button variant="danger" size="sm" onClick={() => void save(pending)}>
                    <Msg of={settingsRetentionSectionRemoveAfter} elems={{ choiceLabel: choiceLabel(Number(pending)) }} />
                  </Button>
                  <Button size="sm" onClick={() => setPending(null)}>
                    {settingsCancel()}
                  </Button>
                </span>
              </CardMessage>
            )}
            {/* What is due is a row of its own: the count is its fact, and
                what happens to it is its description, in the body voice
                (facts carry counts and timestamps, never prose). */}
            <CardRow
              title={settingsRetentionSectionDueForRemoval()}
              description={settingsRetentionSectionDueDetail({ state: state.days === null ? "never" : "set" })}
              facts={<span data-testid="retention-due" role="status">{dueCount(state)}</span>}
            />
            <CardRow
              title={settingsRetentionSectionLastRemoval()}
              facts={<span data-testid="retention-last">{lastRemoval(state)}</span>}
            />
          </>
        )}
      </AsyncBoundary>
      {saved && <CardMessage tone="positive" role="status">{settingsRetentionSectionSaved()}</CardMessage>}
      {error && <CardMessage role="alert">{error}</CardMessage>}
    </Card>
  );
}
