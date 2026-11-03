import type { IntelligenceAvailability, IntelligenceFitBand, IntelligenceTestResult } from "../../api";
import {
  aiAvailabilityAppleIntelligenceDisabled,
  aiAvailabilityAvailable,
  aiAvailabilityDeviceIneligible,
  aiAvailabilityDisabledByFlag,
  aiAvailabilityEgressNotPermitted,
  aiAvailabilityModelNotReady,
  aiAvailabilityNotConfigured,
  aiAvailabilitySdkAbsent,
  aiAvailabilityServerUnreachable,
  aiOriginCloud,
  aiOriginNone,
  aiOriginOnDevice,
  aiOriginThisMac,
  aiSelfTestModelFailed,
  aiSelfTestPrefiltered,
} from "../../copy/gen/ai";
import { sharedFitBandGood, sharedFitBandSome, sharedFitBandStrong, sharedFitBandWeak } from "../../copy/gen/shared";

/* What the AI screen says for the codes the API sends. Each table
 * is a `Record` over the API's own code type, so a state, origin or band the
 * backend adds without a message here is a type error. */

const AVAILABILITY: Record<IntelligenceAvailability["state"], () => string> = {
  available: aiAvailabilityAvailable,
  disabled_by_flag: aiAvailabilityDisabledByFlag,
  sdk_absent: aiAvailabilitySdkAbsent,
  apple_intelligence_disabled: aiAvailabilityAppleIntelligenceDisabled,
  device_ineligible: aiAvailabilityDeviceIneligible,
  model_not_ready: aiAvailabilityModelNotReady,
  not_configured: aiAvailabilityNotConfigured,
  server_unreachable: aiAvailabilityServerUnreachable,
  egress_not_permitted: aiAvailabilityEgressNotPermitted,
};

/** Why a provider can or cannot run, said for the person. */
export const availabilityText = (state: IntelligenceAvailability["state"]): string => AVAILABILITY[state]();

type Origin = Extract<IntelligenceTestResult, { origin: string }>["origin"];

const ORIGIN: Record<Origin, () => string> = {
  none: aiOriginNone,
  on_device: aiOriginOnDevice,
  this_mac: aiOriginThisMac,
  cloud: aiOriginCloud,
};

/** Where a test ran: what RAN, not what is configured. */
export const originText = (origin: Origin): string => ORIGIN[origin]();

/** Why a test has no band to show: the text named no pay, the model failed, or
 *  the provider could not run. Told apart by the keys each outcome carries. */
export function testReason(result: IntelligenceTestResult): string {
  if ("prefiltered" in result && result.prefiltered) return aiSelfTestPrefiltered();
  if ("failure_class" in result) return aiSelfTestModelFailed({ failure: result.failure_class ?? "sdk_error" });
  return availabilityText(result.availability.state);
}

const FIT_BAND: Record<IntelligenceFitBand["key"], () => string> = {
  strong: sharedFitBandStrong,
  good: sharedFitBandGood,
  some: sharedFitBandSome,
  weak: sharedFitBandWeak,
};

/** A fit band by key ("some" reads "Fair"). */
export const fitBandName = (key: IntelligenceFitBand["key"]): string => FIT_BAND[key]();
