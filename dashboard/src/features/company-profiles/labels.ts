import { number as copyNumber } from "../../copy/format";
import type { DataHealth, ReviewReason } from "../../api";
import {
  profilesLabelsCashElection,
  profilesLabelsOneYearGrants,
  profilesLabelsVestedAtGrant,
  profilesLabelsConflictingSignals,
  profilesLabelsCurrent,
  profilesLabelsDirector,
  profilesLabelsEquityVehicle,
  profilesLabelsHeadcount,
  profilesLabelsIncomplete,
  profilesLabelsListed,
  profilesLabelsNoValue,
  profilesLabelsNone,
  profilesLabelsNotCheckedRecently,
  profilesLabelsNothingOnRecord,
  profilesLabelsOptions,
  profilesLabelsPrincipal,
  profilesLabelsSenior,
  profilesLabelsSourcesDisagree,
  profilesLabelsStaff,
  profilesLabelsStale,
  profilesLabelsTicker,
  profilesLabelsVesting,
  profilesLabelsWebsite,
  profilesYesNo,
} from "../../copy/gen/profiles";

/* The profile domain's shared vocabulary: how resolved fields, bands, equity
   vehicles and review reasons are named to the user. */

export const HEALTH_LABEL: Record<DataHealth, string> = {
  get ok() { return profilesLabelsCurrent(); },
  get stale() { return profilesLabelsStale(); },
  get conflict() { return profilesLabelsConflictingSignals(); },
  get missing() { return profilesLabelsIncomplete(); },
};

export const BAND_ORDER = ["senior", "staff", "principal", "director_plus"];
export const BAND_LABEL: Record<string, string> = {
  get senior() { return profilesLabelsSenior(); },
  get staff() { return profilesLabelsStaff(); },
  get principal() { return profilesLabelsPrincipal(); },
  get director_plus() { return profilesLabelsDirector(); },
};

export const FIELD_LABEL: Record<string, string> = {
  get is_public() { return profilesLabelsListed(); },
  get ticker() { return profilesLabelsTicker(); },
  get headcount() { return profilesLabelsHeadcount(); },
  hq_city: "HQ",
  get website() { return profilesLabelsWebsite(); },
  get equity_vehicle() { return profilesLabelsEquityVehicle(); },
  get vesting_schedule() { return profilesLabelsVesting(); },
};

export const VEHICLE_LABEL: Record<string, string> = {
  rsu: "RSUs",
  get options() { return profilesLabelsOptions(); },
  get none() { return profilesLabelsNone(); },
  get cash_election() { return profilesLabelsCashElection(); },
};

/* A company that grants equity one year at a time, or fully vested, has no multi-year
   schedule: the atlas sends a code for the profile's vesting row. A schedule
   ("25/25/25/25") is data and shows as sent. */
export const VESTING_LABEL: Record<string, string> = {
  get one_year_grants() { return profilesLabelsOneYearGrants(); },
  get vested_at_grant() { return profilesLabelsVestedAtGrant(); },
};

export const REASON_TEXT: Record<ReviewReason, string> = {
  get conflict() { return profilesLabelsSourcesDisagree(); },
  get stale() { return profilesLabelsNotCheckedRecently(); },
  get missing() { return profilesLabelsNothingOnRecord(); },
};

/** A yes-or-no field's value ("is it listed?"), in the reader's words. */
export const yesNo = (value: boolean): string => profilesYesNo({ answer: value ? "yes" : "no" });

export function displayValue(field: string, value: unknown): string {
  if (value === null || value === undefined) return profilesLabelsNoValue();
  if (typeof value === "boolean") return yesNo(value);
  if (field === "equity_vehicle") return VEHICLE_LABEL[value as string] ?? String(value);
  if (field === "vesting_schedule") return VESTING_LABEL[value as string] ?? String(value);
  if (typeof value === "number") return copyNumber(value);
  return String(value);
}

/* A URL in a stat grid is a destination, not data. The scheme and the `www.` say
   nothing about the company and cost most of the row's width, so strip them for
   display — the link still points at the full, unmodified URL. */
export function prettyUrl(url: string): string {
  return url
    .trim()
    .replace(/^https?:\/\//i, "")
    .replace(/^www\./i, "")
    .replace(/\/+$/, "");
}

/* A source may send a website without its scheme, so a bare `google.com` has
   to become a real href rather than a relative link into the dashboard. */
export function websiteHref(url: string): string {
  const trimmed = url.trim();
  return /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
}
