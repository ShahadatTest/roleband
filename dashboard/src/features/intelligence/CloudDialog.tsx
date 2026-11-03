/* ---- online model services dialog ---------------------------------------- */

import { FormEvent, useState } from "react";
import {
  CloudLLMProfile,
  CloudLLMProfileInput,
  CloudLLMState,
  api,
} from "../../api";
import { Button, Dialog, Select, Switch } from "../../ui";
import { type DialogError, failed } from "./dialog-error";
import {
  aiAimLineCancel,
  aiCapabilitiesCardSendPostingsToOnlineServices,
  aiCloudDialogADirectApiConnectionBilled,
  aiCloudDialogAddAnOnlineModelService,
  aiCloudDialogAnthropicApi,
  aiCloudDialogApiKey,
  aiCloudDialogCouldNotDelete,
  aiCloudDialogCouldNotSave,
  aiCloudDialogDelete,
  aiCloudDialogDelete2,
  aiCloudDialogEnableThisConnection,
  aiCloudDialogModelId,
  aiCloudDialogName,
  aiCloudDialogOpenaiApi,
  aiCloudDialogOtherOpenaiCompatible,
  aiCloudDialogProvider,
  aiCloudDialogRequiredToTest,
  aiCloudDialogSave,
  aiCloudDialogServerAddressHttps,
} from "../../copy/gen/ai";
import { Msg } from "../../ui/Msg";

const NEW_CLOUD: CloudLLMProfileInput = {
  get name() { return aiCloudDialogOpenaiApi(); },
  provider: "openai",
  base_url: "https://api.openai.com/v1",
  model: "gpt-5.4",
  enabled: false,
  api_key: null,
};

export function CloudDialog({
  profile,
  onClose,
  onChanged,
}: {
  profile: CloudLLMProfile | null;
  onClose: () => void;
  onChanged: (state: CloudLLMState) => void;
}) {
  const [draft, setDraft] = useState<CloudLLMProfileInput>(() =>
    profile
      ? {
          name: profile.name,
          provider: profile.provider,
          base_url: profile.base_url,
          model: profile.model,
          enabled: profile.enabled,
          api_key: null,
        }
      : { ...NEW_CLOUD },
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<DialogError | null>(null);
  // Same two-step arm as the local dialog: one irreversible button, and it
  // must not be reachable by a single stray click next to Save.
  const [armedDelete, setArmedDelete] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      if (profile) await api.updateCloudLLMProfile(profile.id, draft);
      else await api.addCloudLLMProfile(draft);
      onChanged(await api.cloudLLMProfiles());
      onClose();
    } catch (e) {
      setError(failed(aiCloudDialogCouldNotSave(), e));
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!profile) return;
    if (!armedDelete) {
      setArmedDelete(true);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      onChanged(await api.deleteCloudLLMProfile(profile.id));
      onClose();
    } catch (e) {
      setError(failed(aiCloudDialogCouldNotDelete(), e));
      setArmedDelete(false);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog
      isOpen
      onClose={onClose}
      label={aiCloudDialogAddAnOnlineModelService({ choice: (profile) ? "yes" : "no", name: (profile) ? String(profile.name) : "" })}
      width={520}
      className="app-overlay"
    >
      <form className="ledger-form" onSubmit={submit}>
        <h3>{aiCloudDialogAddAnOnlineModelService({ choice: (profile) ? "yes" : "no", name: (profile) ? String(profile.name) : "" })}</h3>
        <p className="intel-dialog-note">
          <Msg of={aiCloudDialogADirectApiConnectionBilled} elems={{ b: <b>{aiCapabilitiesCardSendPostingsToOnlineServices()}</b> }} />
        </p>
        <div className="intel-dialog-grid">
          <div>
            <label htmlFor="cloud-name">{aiCloudDialogName()}</label>
            <input
              id="cloud-name"
              required
              value={draft.name}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            />
          </div>
          <div>
            <label htmlFor="cloud-provider">{aiCloudDialogProvider()}</label>
            <Select
              id="cloud-provider"
              label={aiCloudDialogProvider()}
              value={draft.provider}
              onChange={(provider) => setDraft({ ...draft, provider })}
              options={[
                { value: "openai", label: aiCloudDialogOpenaiApi() },
                { value: "anthropic", label: aiCloudDialogAnthropicApi() },
                { value: "openai_compatible", label: aiCloudDialogOtherOpenaiCompatible() },
              ]}
            />
          </div>
          <div className="is-wide">
            <label htmlFor="cloud-url">{aiCloudDialogServerAddressHttps()}</label>
            <input
              id="cloud-url"
              type="url"
              required
              value={draft.base_url}
              onChange={(e) => setDraft({ ...draft, base_url: e.target.value })}
            />
          </div>
          <div>
            <label htmlFor="cloud-model">{aiCloudDialogModelId()}</label>
            <input
              id="cloud-model"
              required
              value={draft.model}
              onChange={(e) => setDraft({ ...draft, model: e.target.value })}
            />
          </div>
          <div>
            <label htmlFor="cloud-key">{aiCloudDialogApiKey()}</label>
            <input
              id="cloud-key"
              type="password"
              autoComplete="off"
              value={draft.api_key ?? ""}
              placeholder={aiCloudDialogRequiredToTest({ choice: (profile) ? "yes" : "no" })}
              onChange={(e) => setDraft({ ...draft, api_key: e.target.value || null })}
            />
          </div>
        </div>
        <Switch
          className="intel-dialog-check"
          checked={draft.enabled}
          onChange={(enabled) => setDraft({ ...draft, enabled })}
        >
          {aiCloudDialogEnableThisConnection()}
        </Switch>
        {error && (
          <p className="intel-dialog-status is-bad" role="alert">
            <b>{error.lead}</b>
            <span>{error.detail}</span>
          </p>
        )}
        <div className="ledger-form-actions">
          {profile && (
            <Button
              variant="danger"
              className="is-leading"
              disabled={saving}
              aria-pressed={armedDelete}
              aria-label={aiCloudDialogDelete({ choice: (armedDelete) ? "yes" : "no", name: (armedDelete) ? String(profile.name) : "" })}
              onClick={remove}
            >
              {aiCloudDialogDelete2({ choice: (armedDelete) ? "yes" : "no" })}
            </Button>
          )}
          <Button className="ui-btn-strong" onClick={onClose}>
            {aiAimLineCancel()}
          </Button>
          <Button type="submit" variant="primary" disabled={saving}>
            {aiCloudDialogSave({ choice: (saving) ? "yes" : "no" })}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
