import { useState } from "react";
import { api } from "../../api";
import type { UsageGroup, UsageGroupState, UsagePreview, UsageSent, UsageState } from "../../api";
import { errorText } from "../../api/errorText";
import { applySharing, recentEvents } from "../../diagnostics/sharing";
import { calendarDay } from "../../copy/format";
import { formatWhen } from "../../format";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { AsyncBoundary, Button, Switch } from "../../ui";
import { Card, CardMessage, CardRow } from "../../ui/Card";
import {
  privacyConsentTitle,
  privacyNever,
  privacyInstallId,
  privacyInstallIdDetail,
  privacyInstallIdNone,
  privacyLastSent,
  privacyLastSentNever,
  privacyNextSend,
  privacyNextSendCount,
  privacyNextSendDetail,
  privacyResetId,
  privacySaveError,
  privacySentLoadFailed,
  privacySentLoading,
  privacySettingsBlocked,
  privacySettingsIntro,
  privacySettingsLoadFailed,
  privacySettingsRefreshFailed,
  privacySettingsStale,
  privacySettingsTitle,
  privacyShowNext,
  privacyHideSent,
  privacySentCount,
  privacySentFromBrowser,
  privacySentNone,
  privacySentRecently,
  privacySentRecentlyDetail,
  privacyShowSent,
} from "../../copy/gen/privacy";
import { settingsLoading } from "../../copy/gen/settings";
import { GROUPS, consentPayload, groupWords, type ConsentWords } from "../../patterns/privacy/consentCopy";
import "../../patterns/privacy/privacy.css";

/* Settings > Privacy (docs/architecture.md). One switch per kind of
   sharing, committed at once, as Settings' switches are: turning one on
   records the words on this card (the question's title over the switches, the
   group's sentence and the never line in the intro) as what was agreed to;
   turning it off stops it at once, and what was waiting to be sent for it is
   never sent. Below: the install ID and its Reset, when the last send left,
   and the exact body of the next one.

   The card is named by its tab, as every Settings card is; the consent
   question's own title heads the switches it records, so what the record says
   was shown is on screen (patterns/privacy/consentCopy.ts). */

function rowWords(group: UsageGroup, never: string): ConsentWords {
  return { title: privacyConsentTitle(), groups: [groupWords(group)], never };
}

/** One line of what was sent: the daily send's rows (by day, counted) and
 *  what this window sent itself (`diagnostics/sharing.recentEvents`). */
type SentLine = { name: string; when: string; count: number; browser: boolean; at: string };

function sentLines(sent: UsageSent): SentLine[] {
  const fromBackend = sent.events.map((e) => ({
    name: e.name, count: e.count, browser: false, at: e.sent_at,
    when: e.day ? calendarDay(e.day) : formatWhen(e.sent_at),
  }));
  const fromBrowser = recentEvents.map((e) => ({ name: e.event, count: 1, browser: true, at: e.at, when: formatWhen(e.at) }));
  return [...fromBackend, ...fromBrowser].sort((a, b) => Date.parse(b.at) - Date.parse(a.at));
}

export function PrivacySection() {
  const usage = useAsyncResource<UsageState>((signal) => api.usage(signal), []);
  const { mutate } = usage;
  const [busy, setBusy] = useState<UsageGroup | "reset" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<UsagePreview | null>(null);
  const [showSent, setShowSent] = useState(false);
  const sent = useAsyncResource<SentLine[] | null>(
    (signal) => (showSent ? api.usageSent(signal).then(sentLines) : Promise.resolve(null)),
    [showSent],
  );
  // The line every switch's record ends with, shown under the switches.
  const never = privacyNever();

  const turn = async (state: UsageState, group: UsageGroupState, on: boolean) => {
    setBusy(group.group);
    setError(null);
    try {
      const next = await api.saveUsageConsent(
        consentPayload(state, { [group.group]: on }, rowWords(group.group, never)),
      );
      mutate(() => next);
      setPreview(null);
      void applySharing(next);
    } catch (caught) {
      setError(errorText(caught, privacySaveError()));
      void usage.refresh({ preserveData: true });
    } finally {
      setBusy(null);
    }
  };

  const reset = async () => {
    setBusy("reset");
    setError(null);
    try {
      const next = await api.resetUsageInstallId();
      mutate(() => next);
      void applySharing(next);
    } catch (caught) {
      setError(errorText(caught, privacySaveError()));
    } finally {
      setBusy(null);
    }
  };

  const showNext = async () => {
    try {
      setPreview(await api.usagePreview());
    } catch (caught) {
      setError(errorText(caught, privacySaveError()));
    }
  };

  return (
    <Card title={privacySettingsTitle()} intro={<>{privacySettingsIntro()} {never}</>}>
      <AsyncBoundary
        resource={usage}
        failed={privacySettingsLoadFailed()}
        refreshFailed={privacySettingsRefreshFailed()}
        // The row it becomes, as Data retention's: the first kind of sharing.
        skeleton={<CardRow title={groupWords(GROUPS[0]).label} facts={settingsLoading()} />}
      >
        {(state: UsageState) => (
          <>
            {state.blocked_by && (
              <CardMessage tone="info" role="status">{privacySettingsBlocked({ switch: state.blocked_by })}</CardMessage>
            )}
            <h3 className="eyebrow privacy-settings-question">{privacyConsentTitle()}</h3>
            {GROUPS.map((name) => {
              const group = state.groups.find((item) => item.group === name);
              if (!group) return null;
              const words = groupWords(name);
              return (
                <CardRow
                  key={name}
                  toggle={(slot) => (
                    <Switch
                      {...slot}
                      checked={group.status === "shared"}
                      onChange={(on) => void turn(state, group, on)}
                      disabled={busy !== null || state.blocked_by !== null}
                      label={words.label}
                    />
                  )}
                  title={words.label}
                  description={group.status === "stale" ? privacySettingsStale() : words.detail}
                />
              );
            })}
            <CardRow
              title={privacyInstallId()}
              description={privacyInstallIdDetail()}
              facts={state.install_id ?? privacyInstallIdNone()}
              trailing={
                <Button size="sm" onClick={() => void reset()} disabled={busy !== null || !state.install_id}>
                  {privacyResetId()}
                </Button>
              }
            />
            <CardRow
              title={privacyLastSent()}
              facts={state.last_sent_at ? formatWhen(state.last_sent_at) : privacyLastSentNever()}
            />
            <CardRow
              title={privacyNextSend()}
              description={privacyNextSendDetail()}
              facts={<span data-testid="privacy-next-count">{privacyNextSendCount({ count: state.pending_events })}</span>}
              trailing={
                <Button size="sm" onClick={() => void showNext()} disabled={state.pending_events === 0}>
                  {privacyShowNext()}
                </Button>
              }
            />
            <CardRow
              title={privacySentRecently()}
              description={privacySentRecentlyDetail()}
              trailing={
                <Button size="sm" aria-expanded={showSent} onClick={() => setShowSent((open) => !open)}>
                  {showSent ? privacyHideSent() : privacyShowSent()}
                </Button>
              }
            />
            {showSent && (
              <AsyncBoundary
                resource={sent}
                loading={privacySentLoading()}
                failed={privacySentLoadFailed()}
                isEmpty={(lines) => lines.length === 0}
                empty={<CardMessage>{privacySentNone()}</CardMessage>}
              >
                {(lines) => (
                  <ul className="privacy-sent" aria-label={privacySentRecently()}>
                    {lines.map((line, i) => (
                      <li key={`${line.at}-${line.name}-${i}`}>
                        <code>{line.name}</code>
                        <span>{privacySentCount({ count: line.count })}</span>
                        <span>{line.when}</span>
                        {line.browser && <span className="privacy-sent-from">{privacySentFromBrowser()}</span>}
                      </li>
                    ))}
                  </ul>
                )}
              </AsyncBoundary>
            )}
            {preview && (
              <pre className="privacy-preview" aria-label={privacyNextSend()}>
                {JSON.stringify(preview.body, null, 2)}
              </pre>
            )}
            {error && <CardMessage tone="danger" role="alert">{error}</CardMessage>}
          </>
        )}
      </AsyncBoundary>
    </Card>
  );
}
