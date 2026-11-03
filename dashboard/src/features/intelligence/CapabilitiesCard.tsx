import { errorText } from "../../api/errorText";
import { number as copyNumber } from "../../copy/format";
// Card 3: Extended capabilities. One labelled row per capability, each
// carrying where it runs; nothing here is required for the app to work.
//
//   Your own model        · on this computer · the duplicate advisory's engine
//   OS built-in model     · on this computer · experiment, nothing depends on it
//   Online model services · cloud-connected  · none until the user adds one
//
// Configuration lives one step in, behind each row's own dialog. The cloud
// row additionally carries the permission to send posting text off this
// computer (`ai_egress_enabled`), including to services connected later.
import { useCallback, useEffect, useState } from "react";
import {
  CloudLLMProfile,
  CloudLLMState,
  IntelligenceStatus,
  IntelligenceTestResult,
  LocalLLMState,
  LocalServerStatus,
  api,
} from "../../api";
import { Button, Dialog, Icon, Switch } from "../../ui";
import { OriginBadge } from "./OriginBadge";
import { CloudDialog } from "./CloudDialog";
import { LocalModelDialog } from "./LocalModelDialog";
import {
  aiAimLineCancel,
  aiEgressAllow,
  aiEgressDestinations,
  aiEgressDetail,
  aiEgressEmpty,
  aiEgressTitle,
  aiCapabilitiesCardAdd,
  aiCapabilitiesCardAllowSendingPostingsToOnline,
  aiCapabilitiesCardAppleIntelligence,
  aiCapabilitiesCardBlockedOnlineServicesAreSwitched,
  aiCapabilitiesCardConfigure,
  aiCapabilitiesCardConfigureYourOwnModel,
  aiCapabilitiesCardConnectionReadyMs,
  aiCapabilitiesCardEnableAppleIntelligence,
  aiCapabilitiesCardExperimentalWeAreStillTesting,
  aiCapabilitiesCardExtendedCapabilities,
  aiCapabilitiesCardExtendedCapabilities2,
  aiCapabilitiesCardFindsDuplicateJobPostsOnly,
  aiCapabilitiesCardFoundPay,
  aiCapabilitiesCardItFound,
  aiCapabilitiesCardMs,
  aiCapabilitiesCardNoConnectionSaved,
  aiCapabilitiesCardNoKey,
  aiCapabilitiesCardNoPayRangeFound,
  aiCapabilitiesCardNoneConnected,
  aiCapabilitiesCardNotInstalled,
  aiCapabilitiesCardNothingIsSent,
  aiCapabilitiesCardOfOn,
  aiCapabilitiesCardOffNothingIsSent,
  aiCapabilitiesCardOnDevice,
  aiCapabilitiesCardOnlineModelServices,
  aiCapabilitiesCardQuoteFromThePosting,
  aiCapabilitiesCardReady,
  aiCapabilitiesCardReason,
  aiCapabilitiesCardRunningModelNotLoaded,
  aiCapabilitiesCardSaveAConnectionFirstThen,
  aiCapabilitiesCardSendPostingsToOnlineServices,
  aiCapabilitiesCardServerStopped,
  aiCapabilitiesCardStart,
  aiCapabilitiesCardTest,
  aiCapabilitiesCardTest2,
  aiCapabilitiesCardTestAppleIntelligence,
  aiCapabilitiesCardTheExampleSays,
  aiCapabilitiesCardTurnAppleIntelligenceOnTo,
  aiCapabilitiesCardUse,
  aiCapabilitiesCardUseYourOwnModel,
  aiCapabilitiesCardYourOwnModel,
  aiLocalServerActionFailed,
  aiCapabilitiesCardRunning,
} from "../../copy/gen/ai";
import { fmtMoney } from "../../money";
import { Content } from "../../ui/Content";
import { Msg } from "../../ui/Msg";
import { availabilityText, originText, testReason } from "./serverText";


/** A server-supplied sentence used as one clause of a `·`-joined sub-line.
 *  Its trailing full stop is the API's, not ours, and it reads as a stumble
 *  mid-line ("Integration is turned off. · experimental — …"). */
const clause = (text: string) => text.replace(/\.\s*$/, "");

/** What the server strip says about the current probe. */
function serverLabel(server: LocalServerStatus): string {
  if (server.state === "not_configured") return aiCapabilitiesCardNoConnectionSaved();
  if (server.reachable) return aiCapabilitiesCardRunning();
  if (server.state === "model_not_ready") return aiCapabilitiesCardRunningModelNotLoaded();
  if (server.provider === "omlx" && !server.installed) return aiCapabilitiesCardNotInstalled();
  return aiCapabilitiesCardServerStopped();
}

export function CapabilitiesCard({
  status,
  setStatus,
}: {
  status: IntelligenceStatus | null;
  setStatus: (s: IntelligenceStatus) => void;
}) {
  const [local, setLocal] = useState<LocalLLMState | null>(null);
  const [server, setServer] = useState<LocalServerStatus | null>(null);
  const [serverBusy, setServerBusy] = useState(false);
  const [cloud, setCloud] = useState<CloudLLMState | null>(null);
  const [localOpen, setLocalOpen] = useState(false);
  const [cloudOpen, setCloudOpen] = useState<CloudLLMProfile | "new" | null>(null);
  const [saving, setSaving] = useState(false);
  const [savingEgress, setSavingEgress] = useState(false);
  const [egressConfirmOpen, setEgressConfirmOpen] = useState(false);
  const [testingApple, setTestingApple] = useState(false);
  const [appleResult, setAppleResult] = useState<IntelligenceTestResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  // The server probe is separate on purpose: it touches the network, and the
  // rows must render whether or not a server answers.
  const loadServer = useCallback(async () => {
    try {
      setServer(await api.localServerStatus());
    } catch {
      setServer(null);
    }
  }, []);

  useEffect(() => {
    api
      .localLLMProfiles()
      .then(setLocal)
      .catch((e) => setError(errorText(e)));
    api
      .cloudLLMProfiles()
      .then(setCloud)
      .catch((e) => setError(errorText(e)));
    loadServer();
  }, [loadServer]);

  const setLocalEnabled = async (enabled: boolean) => {
    setError(null);
    try {
      setLocal(await api.setLocalLLMEnabled(enabled));
      loadServer();
    } catch (e) {
      setError(errorText(e));
    }
  };

  const controlServer = async (action: "start" | "stop") => {
    setServerBusy(true);
    setError(null);
    try {
      const next = await api.controlLocalServer(action);
      setServer(next);
      if (next.action_ok === false) setError(aiLocalServerActionFailed({ action }));
    } catch (e) {
      setError(errorText(e));
    } finally {
      setServerBusy(false);
    }
  };

  const toggleApple = async () => {
    if (!status || saving) return;
    setSaving(true);
    setError(null);
    try {
      setStatus(await api.setIntelligenceEnabled(!status.enabled));
      setAppleResult(null);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setSaving(false);
    }
  };

  const saveEgress = async (enabled: boolean) => {
    if (!status || savingEgress) return;
    setSavingEgress(true);
    setError(null);
    try {
      setStatus(await api.setAiEgressEnabled(enabled));
      setEgressConfirmOpen(false);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setSavingEgress(false);
    }
  };

  const toggleEgress = () => {
    if (!status || savingEgress) return;
    if (status.routing.egress_enabled) {
      void saveEgress(false);
    } else if (cloud) {
      setError(null);
      setEgressConfirmOpen(true);
    }
  };

  const runAppleTest = async () => {
    setTestingApple(true);
    setError(null);
    setAppleResult(null);
    try {
      setAppleResult(await api.testIntelligence());
    } catch (e) {
      setError(errorText(e));
    } finally {
      setTestingApple(false);
    }
  };

  const activeProfile =
    local?.profiles.find((p) => p.id === local.active_profile_id) ?? local?.profiles[0] ?? null;
  const appleOn = status?.enabled ?? false;
  const egressOn = status?.routing?.egress_enabled ?? false;
  const cloudProfiles = cloud?.profiles ?? [];
  const egressDisabled = savingEgress || status == null || (!egressOn && cloud == null);

  const localOn = Boolean(activeProfile && local?.enabled);
  // A cloud service is ON only when BOTH switches agree. Its own switch is a
  // preference; `ai_egress_enabled` is the permission, and the backend router
  // refuses the tier without it (`RouteReason.EGRESS_BLOCKED`). Counting the
  // preference alone would count a service that cannot run as on.
  const cloudOn = cloudProfiles.filter((p) => p.enabled && egressOn).length;
  const onCount = (localOn ? 1 : 0) + (appleOn ? 1 : 0) + cloudOn;
  const capCount = 2 + cloudProfiles.length;
  const allLocal = cloudOn === 0;

  return (
    <section className="intel-card" aria-label={aiCapabilitiesCardExtendedCapabilities2()}>
      <div className="intel-head">
        <div className="intel-head-title">
          <h2>{aiCapabilitiesCardExtendedCapabilities()}</h2>
        </div>
        <span className="intel-aside">
          <Msg of={aiCapabilitiesCardOfOn} args={{ choice: (allLocal) ? "yes" : "no" }} elems={{ on: <b>{copyNumber(onCount)}</b>, capCount: capCount }} />
        </span>
      </div>

      <div>
        {/* Your own model */}
        <div className="intel-cap">
          <Switch
            checked={localOn}
            disabled={local == null || activeProfile == null}
            onChange={setLocalEnabled}
            label={aiCapabilitiesCardUseYourOwnModel()}
          />
          <span className="intel-cap-mark" aria-hidden="true">
            <Icon name="sparkle" size={18} />
          </span>
          <span>
            <span className="intel-cap-name">{aiCapabilitiesCardYourOwnModel()}</span>
            <span className="intel-cap-sub">
              {activeProfile ? <><Content text={activeProfile.name} />{" · "}</> : ""}
              <Msg of={aiCapabilitiesCardFindsDuplicateJobPostsOnly} elems={{ value: server ? serverLabel(server) : aiCapabilitiesCardNoConnectionSaved() }} />
            </span>
          </span>
          <span className="intel-cap-acts">
            {/* Start is unavailable while the capability is switched off: it
                would launch a server nothing is allowed to use. Stop stays
                available whatever the switch says, so a running process is
                never stranded by turning the row off. */}
            {server?.managed && server.provider === "omlx" && server.installed && (
              <Button
                className="ui-btn-strong"
                disabled={serverBusy || (!localOn && !server.reachable)}
                title={
                  !localOn && !server.reachable
                    ? aiCapabilitiesCardSaveAConnectionFirstThen({ choice: (activeProfile) ? "yes" : "no" })
                    : undefined
                }
                onClick={() => controlServer(server.reachable ? "stop" : "start")}
              >
                <Icon name={server.reachable ? "pause" : "play"} size={16} />
                {aiCapabilitiesCardStart({ choice: (serverBusy) ? "v1" : (server.reachable) ? "v2" : "v3" })}
              </Button>
            )}
            <Button
              variant="icon"
              size="sm"
              aria-label={aiCapabilitiesCardConfigureYourOwnModel()}
              onClick={() => setLocalOpen(true)}
            >
              <Icon name="gear" size={16} />
            </Button>
          </span>
          <OriginBadge origin="local" />
        </div>

        {/* OS built-in model */}
        {status && (
          <div className="intel-cap">
            <Switch
              checked={appleOn}
              disabled={saving}
              onChange={toggleApple}
              label={aiCapabilitiesCardEnableAppleIntelligence()}
            />
            <span className="intel-cap-mark" aria-hidden="true">
              <Icon name="sun" size={18} />
            </span>
            <span>
              <span className="intel-cap-name">{aiCapabilitiesCardAppleIntelligence()}</span>
              <span className="intel-cap-sub">
                <Msg of={aiCapabilitiesCardExperimentalWeAreStillTesting} elems={{ value: status.availability.ok ? aiCapabilitiesCardReady() : clause(availabilityText(status.availability.state)) }} />
              </span>
            </span>
            <span className="intel-cap-acts">
              <Button
                className="ui-btn-strong"
                aria-label={aiCapabilitiesCardTestAppleIntelligence()}
                disabled={testingApple || !appleOn}
                title={appleOn ? undefined : aiCapabilitiesCardTurnAppleIntelligenceOnTo()}
                onClick={runAppleTest}
              >
                {aiCapabilitiesCardTest({ choice: (testingApple) ? "yes" : "no" })}
              </Button>
            </span>
            <OriginBadge origin="local" />
          </div>
        )}
        {appleResult && <AppleResult result={appleResult} />}

        {/* Online model services */}
        {cloudProfiles.length === 0 ? (
          <div className="intel-cap is-future">
            {/* A standing permission, settable before any service exists:
                the same shape as the MCP card's connect gate, which you may
                allow before setting up an app. It is the SAME egress flag the
                connected-service row toggles, so the answer survives adding a
                service later; nothing can be sent while no service exists
                either way, because there is nowhere to send it. */}
            <Switch
              checked={egressOn}
              disabled={egressDisabled}
              onChange={toggleEgress}
              label={aiCapabilitiesCardSendPostingsToOnlineServices()}
            />
            <span className="intel-cap-mark" aria-hidden="true">
              <Icon name="plus" size={18} />
            </span>
            <span>
              <span className="intel-cap-name">{aiCapabilitiesCardOnlineModelServices()}</span>
              <span className="intel-cap-sub">
                {aiCapabilitiesCardNoneConnected()}{" "}
                {aiCapabilitiesCardNothingIsSent({ choice: (egressOn) ? "yes" : "no" })}
              </span>
            </span>
            <span className="intel-cap-acts">
              <Button className="ui-btn-strong" onClick={() => setCloudOpen("new")}>
                {aiCapabilitiesCardAdd()}
              </Button>
            </span>
            <OriginBadge origin="cloud" />
          </div>
        ) : (
          <>
            <div className="intel-cap">
              <Switch
                checked={egressOn}
                disabled={egressDisabled}
                onChange={toggleEgress}
                label={aiCapabilitiesCardSendPostingsToOnlineServices()}
              />
              <span className="intel-cap-mark" aria-hidden="true">
                <Icon name="cloud" size={18} />
              </span>
              <span>
                <span className="intel-cap-name">{aiCapabilitiesCardSendPostingsToOnlineServices()}</span>
                <span className="intel-cap-sub">
                  {aiCapabilitiesCardOffNothingIsSent({ choice: (egressOn) ? "yes" : "no" })}
                </span>
              </span>
              <span className="intel-cap-acts">
                <Button className="ui-btn-strong" onClick={() => setCloudOpen("new")}>
                  {aiCapabilitiesCardAdd()}
                </Button>
              </span>
              <OriginBadge origin="cloud" />
            </div>
            {cloudProfiles.map((profile) => (
              <CloudRow
                key={profile.id}
                profile={profile}
                egressOn={egressOn}
                onChanged={setCloud}
                onConfigure={() => setCloudOpen(profile)}
                onError={setError}
              />
            ))}
          </>
        )}
      </div>

      {error && !egressConfirmOpen && <div className="intel-error" role="alert">{error}</div>}

      {egressConfirmOpen && (
        <Dialog
          isOpen
          onClose={() => { if (!savingEgress) setEgressConfirmOpen(false); }}
          closeOnScrim={!savingEgress}
          label={aiEgressTitle()}
          className="app-overlay"
          surface="solid"
          width={520}
        >
          <div className="ledger-form">
            <h3>{aiEgressTitle()}</h3>
            <p className="intel-dialog-note">{aiEgressDetail()}</p>
            {cloudProfiles.length > 0 ? (
              <div>
                <h3>{aiEgressDestinations()}</h3>
                <ul className="intel-egress-destinations">
                  {cloudProfiles.map((profile) => (
                    <li key={profile.id}>
                      <Content text={profile.name} />
                      <Content className="intel-dialog-note" text={profile.base_url} />
                    </li>
                  ))}
                </ul>
              </div>
            ) : <p className="intel-dialog-note">{aiEgressEmpty()}</p>}
            {error && <div className="intel-error" role="alert">{error}</div>}
            <div className="ledger-form-actions">
              <Button disabled={savingEgress} onClick={() => setEgressConfirmOpen(false)}>
                {aiAimLineCancel()}
              </Button>
              <Button variant="primary" disabled={savingEgress} onClick={() => saveEgress(true)}>
                {aiEgressAllow()}
              </Button>
            </div>
          </div>
        </Dialog>
      )}

      {localOpen && local && (
        <LocalModelDialog
          state={local}
          onClose={() => setLocalOpen(false)}
          onChanged={(next) => {
            setLocal(next);
            loadServer();
          }}
        />
      )}
      {cloudOpen && (
        <CloudDialog
          profile={cloudOpen === "new" ? null : cloudOpen}
          onClose={() => setCloudOpen(null)}
          onChanged={setCloud}
        />
      )}
    </section>
  );
}

/* ---- built-in model's transient test result ------------------------------ */

/* An amount in the currency the posting states. One that states none shows
 * the figure alone: a symbol would claim a currency nobody stated. */
const amount = (n: number, currency: string | null) => (currency ? fmtMoney(n, currency) : copyNumber(n));

function band(min: number | null, max: number | null, currency: string | null) {
  if (min == null && max == null) return "—";
  if (min != null && max != null) return `${amount(min, currency)}–${amount(max, currency)}`;
  return amount((min ?? max) as number, currency);
}

function AppleResult({ result }: { result: IntelligenceTestResult }) {
  // Four outcomes, each with its own keys: only an answer carries a verdict,
  // and only a model that ran says how long it took and where it ran.
  const answered = "grounded" in result ? result : null;
  const ran = "origin" in result ? result : null;
  const ex = answered?.extracted ?? null;
  const rejected = answered?.rejected_ungrounded ?? false;
  const matched =
    result.expected != null &&
    ex != null &&
    ex.base_min === result.expected.base_min &&
    ex.base_max === result.expected.base_max;
  const tone = !result.ok ? "is-bad" : rejected ? "is-warn" : "";
  const headline = aiCapabilitiesCardNoPayRangeFound({ choice: (!result.ok) ? "v1" : (rejected) ? "v2" : (matched) ? "v3" : (answered?.grounded) ? "v4" : "v5" });

  return (
    <dl className={`intel-result ${tone}`} role="status">
      <div className="intel-result-head">
        {headline}
        <span className="intel-result-meta">
          {[
            ran && ran.latency_ms != null ? aiCapabilitiesCardMs({ latency_ms: ran.latency_ms }) : null,
            ran ? (ran.origin === "on_device" ? aiCapabilitiesCardOnDevice() : originText(ran.origin)) : null,
          ]
            .filter(Boolean)
            .join(" · ")}
        </span>
      </div>
      {result.expected && (
        <>
          <dt>{aiCapabilitiesCardTheExampleSays()}</dt>
          <dd>
            {band(result.expected.base_min, result.expected.base_max, result.expected.currency)}
          </dd>
        </>
      )}
      {ex && (
        <>
          <dt>{aiCapabilitiesCardItFound()}</dt>
          <dd>
            {aiCapabilitiesCardFoundPay({ band: band(ex.base_min, ex.base_max, ex.currency), basis: ex.pay_basis, period: ex.pay_period })}
          </dd>
          <dt>{aiCapabilitiesCardQuoteFromThePosting()}</dt>
          <dd className="is-quote">{ex.source_snippet ?? "—"}</dd>
        </>
      )}
      {!ex && (
        <>
          <dt>{aiCapabilitiesCardReason()}</dt>
          <dd>{testReason(result)}</dd>
        </>
      )}
    </dl>
  );
}

/* ---- cloud service row + dialog ------------------------------------------ */

/** One connected online service.
 *
 *  Two switches stand between this row and the network, and they mean
 *  different things: `egressOn` is the permission (may anything leave this
 *  computer at all), `profile.enabled` is the preference (use THIS service).
 *  Both are settable in advance and in either order (deliberately, the same
 *  way the permission is settable before any service exists), so the row
 *  reports the COMBINATION rather than either switch alone, and the action
 *  that reaches the vendor is available only when both agree. */
function CloudRow({
  profile,
  egressOn,
  onChanged,
  onConfigure,
  onError,
}: {
  profile: CloudLLMProfile;
  egressOn: boolean;
  onChanged: (state: CloudLLMState) => void;
  onConfigure: () => void;
  onError: (message: string | null) => void;
}) {
  const [testing, setTesting] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const setEnabled = async (enabled: boolean) => {
    setSaving(true);
    onError(null);
    try {
      await api.updateCloudLLMProfile(profile.id, {
        name: profile.name,
        provider: profile.provider,
        base_url: profile.base_url,
        model: profile.model,
        enabled,
        api_key: null,
      });
      onChanged(await api.cloudLLMProfiles());
    } catch (e) {
      onError(errorText(e));
    } finally {
      setSaving(false);
    }
  };

  const usable = profile.enabled && egressOn;
  // A row that cannot run says which switch is holding it, because the two
  // sit on different rows and only one of them is beside this one.
  const reason = aiCapabilitiesCardAllowSendingPostingsToOnline({ choice: (!profile.enabled) ? "yes" : "no", name: (!profile.enabled) ? String(profile.name) : "" });
  // Never the word "off" beside a switch the user can see is ON: this row's
  // own switch says nothing about the permission a row above it holds, so the
  // blocked state names the thing that is actually holding it.
  const state = aiCapabilitiesCardBlockedOnlineServicesAreSwitched({ choice: (usable) ? "v1" : (!profile.enabled) ? "v2" : "v3" });

  // Testing authenticates to the vendor with the saved key. It carries no job
  // text (that path is gated in `intelligence.registry`), but it is still a
  // request this computer makes to a service the user has switched off, which
  // is exactly what the switches are there to prevent.
  const test = async () => {
    if (!usable) return;
    setTesting(true);
    setNote(null);
    onError(null);
    try {
      const result = await api.testCloudLLMProfile(profile.id);
      setNote(aiCapabilitiesCardConnectionReadyMs({ latency_ms: result.latency_ms }));
    } catch (e) {
      onError(errorText(e));
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="intel-cap">
      <Switch
        checked={profile.enabled}
        disabled={saving}
        onChange={setEnabled}
        label={aiCapabilitiesCardUse({ name: String(profile.name) })}
      />
      <span className="intel-cap-mark" aria-hidden="true">
        <Icon name="cloud" size={18} />
      </span>
      <span>
        <Content className="intel-cap-name" text={profile.name} />
        <span className="intel-cap-sub">
          <Content text={profile.model} /> · {aiCapabilitiesCardNoKey({ choice: (profile.has_api_key) ? "yes" : "no" })} · {state}
          {note ? ` · ${note}` : ""}
        </span>
      </span>
      <span className="intel-cap-acts">
        {/* Setup stays reachable whatever the switches say: it is the only
            way to correct the connection that made the row unusable. Testing
            does not: it is use. */}
        <Button
          className="ui-btn-strong"
          aria-label={aiCapabilitiesCardTest2({ name: String(profile.name) })}
          disabled={testing || !usable}
          title={usable ? undefined : reason}
          onClick={test}
        >
          {aiCapabilitiesCardTest({ choice: (testing) ? "yes" : "no" })}
        </Button>
        <Button
          variant="icon"
          size="sm"
          aria-label={aiCapabilitiesCardConfigure({ name: String(profile.name) })}
          onClick={onConfigure}
        >
          <Icon name="gear" size={16} />
        </Button>
      </span>
      <OriginBadge origin="cloud" />
    </div>
  );
}
