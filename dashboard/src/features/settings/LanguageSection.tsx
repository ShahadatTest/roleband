import { useState, useSyncExternalStore } from "react";
import { api } from "../../api";
import { errorText } from "../../api/errorText";
import { LOCALES, saveChoice } from "../../copy/activate";
import { country, regionSample, regionCountry } from "../../copy/format";
import { choice, subscribe, copyCheckOn, regionTag, type Choice } from "../../copy/runtime";
import {
  settingsLanguageCheck,
  settingsLanguageDescription,
  settingsSaveFailed,
  settingsLanguageIntro,
  settingsLanguageLabel,
  settingsLanguagePartial,
  settingsLanguageTitle,
  settingsRegionAutomatic,
  settingsRegionDescription,
  settingsRegionLabel,
  settingsRegionOption,
} from "../../copy/gen/settings";
import { Card, CardMessage, CardRow } from "../../ui/Card";
import { Select } from "../../ui";
import type { SelectOption } from "../../ui";

// Settings > Language and region (docs/copy.md).
// Two controls, saved on change. Language picks the catalog; region picks how
// numbers and dates are written, "As your system" following the operating
// system. A change is saved for the account, then applied: the UI remounts
// under the new language, keeping the URL and every provider's data.
// A pseudo language is a device-only check, listed with the copy-check flag
// and never saved for the account.

/** Regions offered besides the system's: one per country, each shown with a
 *  sample of how it writes numbers and dates. */
// The regions of the languages RoleBand speaks: English, Spanish and Chinese.
import { REGIONS } from "../../copy/gen/index";
const SYSTEM = "system";

function languageOptions(): SelectOption<string>[] {
  const check = copyCheckOn();
  return LOCALES.filter((l) => l.status !== "pseudo" || check).map((l) => ({
    value: l.code,
    label:
      l.status === "beta" ? settingsLanguagePartial({ name: l.name })
        : l.status === "pseudo" ? settingsLanguageCheck({ name: l.name })
          : l.name,
  }));
}

function regionOptions(current: string | null): SelectOption<string>[] {
  return [
    { value: SYSTEM, label: settingsRegionAutomatic() },
    ...[...REGIONS, ...(current && !REGIONS.includes(current) ? [current] : [])].map((tag) => ({
      value: tag,
      label: settingsRegionOption({ country: country(regionCountry(tag)), ...regionSample(tag) }),
    })),
  ];
}

export function LanguageSection() {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const now = useSyncExternalStore(subscribe, choice);

  const change = async (next: Choice) => {
    setSaving(true);
    setError(null);
    try {
      await saveChoice(next, api.saveLocale);
    } catch (caught) {
      setError(errorText(caught, settingsSaveFailed()));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card title={settingsLanguageTitle()} intro={settingsLanguageIntro()}>
      <CardRow
        title={settingsLanguageLabel()}
        description={settingsLanguageDescription()}
        trailing={
          <Select
            label={settingsLanguageLabel()}
            value={now.language}
            onChange={(language) => void change({ language, region: now.region })}
            options={languageOptions()}
            disabled={saving}
          />
        }
      />
      <CardRow
        title={settingsRegionLabel()}
        description={settingsRegionDescription(regionSample(regionTag()))}
        trailing={
          <Select
            label={settingsRegionLabel()}
            value={now.region ?? SYSTEM}
            onChange={(region) => void change({ language: now.language, region: region === SYSTEM ? null : region })}
            options={regionOptions(now.region)}
            disabled={saving}
          />
        }
      />
      {error && <CardMessage role="alert">{error}</CardMessage>}
    </Card>
  );
}
