import { ChangeEvent, FormEvent, useEffect, useRef, useState } from "react";
import {
  LocalLLMParameters,
  LocalLLMProfile,
  LocalLLMProfileInput,
  LocalLLMState,
  LocalLLMTestResult,
  api,
} from "../../api";
import { Button, Dialog, Select, Switch } from "../../ui";
import { type DialogError, failed } from "./dialog-error";
import {
  aiAimLineCancel,
  aiCapabilitiesCardUse,
  aiCloudDialogApiKey,
  aiCloudDialogCouldNotDelete,
  aiCloudDialogCouldNotSave,
  aiCloudDialogDelete,
  aiCloudDialogDelete2,
  aiCloudDialogModelId,
  aiCloudDialogName,
  aiCloudDialogOtherOpenaiCompatible,
  aiCloudDialogSave,
  aiLocalModelDialogAModelServerYouRun,
  aiLocalModelDialogConfigureYourOwnModel,
  aiLocalModelDialogConnectionIncomplete,
  aiLocalModelDialogCouldNotReachTheModel,
  aiLocalModelDialogCouldNotSwitchConnection,
  aiLocalModelDialogDefaultName,
  aiLocalModelDialogEnableModelThinking,
  aiLocalModelDialogGenerationAndReasoningParameters,
  aiLocalModelDialogMaxTokens,
  aiLocalModelDialogMs,
  aiLocalModelDialogOmlxManaged,
  aiLocalModelDialogOptional,
  aiLocalModelDialogSavedConnections,
  aiLocalModelDialogServerAddress,
  aiLocalModelDialogServerType,
  aiLocalModelDialogTemperature,
  aiLocalModelDialogTestConnection,
  aiLocalModelDialogThinkingBudget,
  aiLocalModelDialogTimeoutS,
  aiLocalModelDialogTopP,
  aiLocalModelDialogYourOwnModel,
  aiLocalTestMaxTokens,
  aiLocalTestSucceeded,
} from "../../copy/gen/ai";
import { Msg } from "../../ui/Msg";

const DEFAULT_PARAMETERS: LocalLLMParameters = {
  max_tokens: 32768,
  temperature: 0.2,
  top_p: 0.95,
  top_k: 0,
  min_p: 0,
  repetition_penalty: 1,
  presence_penalty: 0,
  frequency_penalty: 0,
  seed: null,
  enable_thinking: true,
  thinking_budget: 2048,
  timeout_seconds: 180,
};

const NEW_LOCAL: LocalLLMProfileInput = {
  get name() { return aiLocalModelDialogDefaultName(); },
  provider: "omlx",
  base_url: "http://127.0.0.1:8000/v1",
  model: "Ornith-1.0-35B-5bit-mlx",
  api_key: null,
  parameters: DEFAULT_PARAMETERS,
};

/* ---- your own model dialog ----------------------------------------------- */

const draftFor = (profile: LocalLLMProfile | null): LocalLLMProfileInput => profile
  ? {
      name: profile.name,
      provider: profile.provider,
      base_url: profile.base_url,
      model: profile.model,
      api_key: null,
      parameters: { ...profile.parameters },
    }
  : { ...NEW_LOCAL, parameters: { ...DEFAULT_PARAMETERS } };

export function LocalModelDialog({
  state,
  onClose,
  onChanged,
}: {
  state: LocalLLMState;
  onClose: () => void;
  onChanged: (state: LocalLLMState) => void;
}) {
  const editing: LocalLLMProfile | null =
    state.profiles.find((p) => p.id === state.active_profile_id) ?? state.profiles[0] ?? null;
  const [draft, setDraft] = useState<LocalLLMProfileInput>(() => draftFor(editing));
  const [saving, setSaving] = useState(false);
  const [selecting, setSelecting] = useState(false);
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<LocalLLMTestResult | null>(null);
  const [error, setError] = useState<DialogError | null>(null);
  // Delete is armed by a first click and only acts on a second. Nothing else
  // in this dialog is irreversible, and a saved connection is not recoverable
  // from the row that lost it.
  const [armedDelete, setArmedDelete] = useState(false);

  // The draft resets when the reader moves to ANOTHER profile — keyed on the
  // profile's id. `editing` itself is derived from the `state` prop, so its
  // object identity changes on every refresh (a test result, a save); keying
  // on the object would wipe what the reader is typing each time.
  const editingId = editing?.id ?? null;
  const editingRef = useRef(editing);
  editingRef.current = editing;
  useEffect(() => {
    setDraft(draftFor(editingRef.current));
    setResult(null);
    setArmedDelete(false);
  }, [editingId]);

  const selectProfile = async (id: string) => {
    if (state.active_profile_id === id) return;
    setSelecting(true);
    setError(null);
    try {
      onChanged(await api.selectLocalLLMProfile(id));
    } catch (e) {
      setError(failed(aiLocalModelDialogCouldNotSwitchConnection(), e));
    } finally {
      setSelecting(false);
    }
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      if (editing) await api.updateLocalLLMProfile(editing.id, draft);
      else await api.addLocalLLMProfile(draft);
      onChanged(await api.localLLMProfiles());
      onClose();
    } catch (e) {
      setError(failed(aiCloudDialogCouldNotSave(), e));
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!editing) return;
    if (!armedDelete) {
      setArmedDelete(true);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      onChanged(await api.deleteLocalLLMProfile(editing.id));
      onClose();
    } catch (e) {
      setError(failed(aiCloudDialogCouldNotDelete(), e));
      setArmedDelete(false);
    } finally {
      setSaving(false);
    }
  };

  const test = async () => {
    if (!editing) return;
    setTesting(true);
    setError(null);
    setResult(null);
    try {
      setResult(await api.testLocalLLMProfile(editing.id, draft));
    } catch (e) {
      setError(failed(aiLocalModelDialogCouldNotReachTheModel(), e));
    } finally {
      setTesting(false);
    }
  };

  const num = (key: keyof LocalLLMParameters) => ({
    value: String(draft.parameters[key] ?? ""),
    onChange: (e: ChangeEvent<HTMLInputElement>) =>
      setDraft({
        ...draft,
        parameters: {
          ...draft.parameters,
          [key]: e.target.value === "" ? null : Number(e.target.value),
        },
      }),
  });

  return (
    <Dialog
      isOpen
      onClose={onClose}
      label={aiLocalModelDialogConfigureYourOwnModel()}
      width={560}
      className="app-overlay"
    >
      <form className="ledger-form" onSubmit={submit}>
        <h3>{aiLocalModelDialogYourOwnModel()}</h3>
        <p className="intel-dialog-note">
          {aiLocalModelDialogAModelServerYouRun()}
        </p>

        {state.profiles.length > 1 && (
          <div className="intel-profile-list" role="radiogroup" aria-label={aiLocalModelDialogSavedConnections()}>
            {state.profiles.map((p) => (
              <label key={p.id}>
                <input
                  type="radio"
                  name="local-profile"
                  checked={p.id === state.active_profile_id}
                  disabled={selecting || saving || testing}
                  onChange={() => selectProfile(p.id)}
                  aria-label={aiCapabilitiesCardUse({ name: String(p.name) })}
                />
                {p.name}
                <span className="intel-profile-meta">{p.model}</span>
              </label>
            ))}
          </div>
        )}

        <div className="intel-dialog-grid">
          <div>
            <label htmlFor="local-name">{aiCloudDialogName()}</label>
            <input
              id="local-name"
              required
              value={draft.name}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            />
          </div>
          <div>
            <label htmlFor="local-provider">{aiLocalModelDialogServerType()}</label>
            <Select
              id="local-provider"
              label={aiLocalModelDialogServerType()}
              value={draft.provider}
              onChange={(provider) => setDraft({ ...draft, provider })}
              options={[
                { value: "omlx", label: aiLocalModelDialogOmlxManaged() },
                { value: "openai_compatible", label: aiCloudDialogOtherOpenaiCompatible() },
              ]}
            />
          </div>
          <div className="is-wide">
            <label htmlFor="local-url">{aiLocalModelDialogServerAddress()}</label>
            <input
              id="local-url"
              type="url"
              required
              value={draft.base_url}
              onChange={(e) => setDraft({ ...draft, base_url: e.target.value })}
            />
          </div>
          <div>
            <label htmlFor="local-model">{aiCloudDialogModelId()}</label>
            <input
              id="local-model"
              required
              value={draft.model}
              onChange={(e) => setDraft({ ...draft, model: e.target.value })}
            />
          </div>
          <div>
            <label htmlFor="local-key">{aiCloudDialogApiKey()}</label>
            <input
              id="local-key"
              type="password"
              autoComplete="off"
              value={draft.api_key ?? ""}
              placeholder={aiLocalModelDialogOptional({ choice: (editing) ? "yes" : "no" })}
              onChange={(e) => setDraft({ ...draft, api_key: e.target.value || null })}
            />
          </div>
        </div>

        <details className="intel-params">
          <summary>{aiLocalModelDialogGenerationAndReasoningParameters()}</summary>
          <div className="intel-dialog-grid">
            <div>
              <label htmlFor="local-max-tokens">{aiLocalModelDialogMaxTokens()}</label>
              <input id="local-max-tokens" type="number" {...num("max_tokens")} />
            </div>
            <div>
              <label htmlFor="local-temperature">{aiLocalModelDialogTemperature()}</label>
              <input id="local-temperature" type="number" step="0.05" {...num("temperature")} />
            </div>
            <div>
              <label htmlFor="local-top-p">{aiLocalModelDialogTopP()}</label>
              <input id="local-top-p" type="number" step="0.05" {...num("top_p")} />
            </div>
            <div>
              <label htmlFor="local-timeout">{aiLocalModelDialogTimeoutS()}</label>
              <input id="local-timeout" type="number" {...num("timeout_seconds")} />
            </div>
            <div>
              <label htmlFor="local-thinking-budget">{aiLocalModelDialogThinkingBudget()}</label>
              <input id="local-thinking-budget" type="number" {...num("thinking_budget")} />
            </div>
            {/* The one non-numeric parameter, and the only switch in this
                dialog — so it wears the same switch as every other on/off in
                the Intelligence screen rather than a bare checkbox. */}
            <Switch
              className="intel-dialog-check"
              checked={draft.parameters.enable_thinking}
              onChange={(enable_thinking) =>
                setDraft({
                  ...draft,
                  parameters: { ...draft.parameters, enable_thinking },
                })
              }
            >
              {aiLocalModelDialogEnableModelThinking()}
            </Switch>
          </div>
        </details>

        {result && (
          <p className={`intel-dialog-status ${result.ok ? "is-ok" : "is-warn"}`} role="status">
            <b>{aiLocalModelDialogConnectionIncomplete({ choice: (result.ok) ? "yes" : "no" })}</b>
            <span>{result.finish_reason === "length" ? aiLocalTestMaxTokens() : aiLocalTestSucceeded()}</span>
            {result.metrics?.wall_time_ms != null && (
              <span className="intel-dialog-status-meta"><Msg of={aiLocalModelDialogMs} elems={{ wall_time_ms: result.metrics.wall_time_ms }} /></span>
            )}
          </p>
        )}
        {error && (
          <p className="intel-dialog-status is-bad" role="alert">
            <b>{error.lead}</b>
            <span>{error.detail}</span>
          </p>
        )}

        <div className="ledger-form-actions">
          {editing && (
            <>
              {/* `is-leading` puts the irreversible button at the other end of
                  the row from Save; the armed label names what is lost. */}
              <Button
                variant="danger"
                className="is-leading"
                disabled={saving || selecting}
                aria-pressed={armedDelete}
                aria-label={aiCloudDialogDelete({ choice: (armedDelete) ? "yes" : "no", name: (armedDelete) ? String(editing.name) : "" })}
                onClick={remove}
              >
                {aiCloudDialogDelete2({ choice: (armedDelete) ? "yes" : "no" })}
              </Button>
              <Button className="ui-btn-strong" disabled={testing || selecting} onClick={test}>
                {aiLocalModelDialogTestConnection({ choice: (testing) ? "yes" : "no" })}
              </Button>
            </>
          )}
          <Button className="ui-btn-strong" onClick={onClose}>
            {aiAimLineCancel()}
          </Button>
          <Button type="submit" variant="primary" disabled={saving || selecting}>
            {aiCloudDialogSave({ choice: (saving) ? "yes" : "no" })}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
