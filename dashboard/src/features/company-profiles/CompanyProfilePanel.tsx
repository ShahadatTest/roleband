import "../../patterns/figure-table.css";
import { calendarDay, country, list, number as copyNumber, percent } from "../../copy/format";
import { levelName, sourceName } from "../../copy/vocab";
import { errorText } from "../../api/errorText";
import { ResourceLoadState } from "../../ui/ResourceLoadState";
import { useCallback, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { CompanyProfileDetail, LevelGuide, LevelGuideCompany, ProfileField, ReviewItem, api } from "../../api";
import { fmtComp, fmtCompIn } from "../../format";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { useSourceSwitch } from "../../context/SyncState";
import { Button } from "../../ui/Button";
import { EmptyState } from "../../ui/EmptyState";
import { CompanyOffices } from "./CompanyOffices";
import { CompanyLogo } from "./CompanyLogo";
import { FieldReview, PinnedField } from "./FieldReview";
import { StockPricePanel } from "./StockPricePanel";
import { notOnBoardSentence } from "../../patterns/companies/CompanyChip";
import { ladderOf, levelCode } from "../../patterns/levels/levelGuide";
import {
  BAND_LABEL,
  BAND_ORDER,
  FIELD_LABEL,
  HEALTH_LABEL,
  REASON_TEXT,
  VEHICLE_LABEL,
  VESTING_LABEL,
  displayValue,
  prettyUrl,
  websiteHref,
  yesNo,
} from "./labels";
import {
  profilesCompanyProfilePanel0Open,
  profilesCompanyProfilePanelBand,
  profilesCompanyProfilePanelBase,
  profilesCompanyProfilePanelBaseStockBonus,
  profilesCompanyProfilePanelBenefits,
  profilesCompanyProfilePanelBonus,
  profilesCompanyProfilePanelCompBaseline,
  profilesCompanyProfilePanelComposition,
  profilesCompanyProfilePanelConflictingSignal,
  profilesCompanyProfilePanelCountries,
  profilesCompanyProfilePanelLevel,
  profilesCompanyProfilePanelLoading,
  profilesCompanyProfilePanelNoCompBandsYet,
  profilesCompanyProfilePanelNoLevelInThisCompany,
  profilesCompanyProfilePanelNotOnYourBoard,
  profilesCompanyProfilePanelOfficesOpenRoles,
  profilesCompanyProfilePanelOpen,
  profilesCompanyProfilePanelProfileUnavailable,
  profilesCompanyProfilePanelRetry,
  profilesCompanyProfilePanelSays,
  profilesCompanyProfilePanelSeeOpenRoles,
  profilesCompanyProfilePanelSeeOpenRolesAt,
  profilesCompanyProfilePanelStock,
  profilesCompanyProfilePanelTotalComp,
  profilesCompanyProfilePanelValuesComeFromTheSource,
  profilesCompanyProfilePanelWhatARoleAtEach,
  profilesCompanyProfilePanelWhereThisCompanyIsHiring,
  profilesBenefitsCategory,
  profilesBenefitsEstimate,
  profilesBenefitsAlsoListed,
  profilesLevelBaseBelowLower,
  profilesLevelBaseBonus,
  profilesLevelBaseNoCode,
  profilesLevelBaseNoStock,
  profilesLevelBaseNone,
  profilesLevelBaseUnknown,
  profilesEquityPolicy,
  profilesLevelBaseSub,
  profilesBenefitsInCountry,
  profilesBenefitsMentions,
  profilesBenefitsNotCollected,
  profilesBenefitsOtherWordings,
  profilesBenefitsShared,
  profilesFieldNotCovered,
  profilesNotCovered,
  profilesBenefitsType,
  profilesBenefitsUnreviewed,
  profilesBenefitsUnscoped,
  profilesOfferBonusRule,
  profilesOfferChecked,
  profilesOfferEquityRule,
  profilesOfferFact,
  profilesOfferHeading,
  profilesOfferNotResearched,
  profilesOfferRefresh,
  profilesOfferSearchedNotFound,
  profilesOfferSignOn,
  profilesOfferSub,
} from "../../copy/gen/profiles";
import { commonTryAgain } from "../../copy/gen/common";
import { sharedRefreshFailed, sharedTcFull } from "../../copy/gen/shared";
import { Abbr } from "../../ui/Abbr";
import { Msg } from "../../ui/Msg";
import { Content } from "../../ui/Content";
import { SourceLabel, type SourceNames } from "./SourceLabel";

// Renders a value together with how much we should trust it: which source won,
// how fresh that claim is, and, critically, who disagrees. A field awaiting
// review carries its own resolution controls (FieldReview), so a value is
// fixed exactly where it is read.
function Field({
  name,
  field,
  review,
  enriching,
  slug,
  sourceNames,
  onResolved,
  searched = false,
  notCoveredBy = null,
}: {
  name: string;
  field: ProfileField;
  review?: ReviewItem;
  enriching: boolean;
  slug: string;
  sourceNames: SourceNames;
  onResolved: () => void;
  /** The atlas searched for this and found nothing: say so, not a bare dash. */
  searched?: boolean;
  /** The plugin answering this field has not read the company:
   *  name it, never a bare dash that reads as "unknown". */
  notCoveredBy?: string | null;
}) {
  const { value, source, freshness, is_manual, conflicts } = field;

  // The chip only earns its space when it says something the footer does not.
  // The footer credits every plugin answering this profile, so its rows carry
  // no chip: identical plugin chips down one column read as noise and bury
  // the rows that actually differ (a manual pin, an inference, a filing).
  const showSource = Boolean(source) && (is_manual || !(source! in sourceNames));

  let shown: ReactNode;
  if ((value === null || value === undefined) && notCoveredBy)
    shown = <Msg of={profilesFieldNotCovered} elems={{ plugin: <Content text={notCoveredBy} /> }} />;
  else if (value === null || value === undefined) shown = searched ? profilesOfferSearchedNotFound() : "—";
  else if (typeof value === "boolean") shown = yesNo(value);
  else if (name === "equity_vehicle")
    shown = VEHICLE_LABEL[value as string] ?? String(value);
  else if (name === "vesting_schedule")
    shown = VESTING_LABEL[value as string] ?? String(value);
  else if (name === "headcount") shown = copyNumber((value as number));
  else if (name === "website") shown = prettyUrl(String(value));
  else shown = String(value);

  // The website is the one field whose value is somewhere to GO.
  const href =
    name === "website" && typeof value === "string" && value.trim()
      ? websiteHref(value)
      : null;

  // Open only in the mode: the row keeps its warning rule and says WHY it is
  // flagged either way, but the controls that settle it are asked for.
  const open = Boolean(review) && enriching;

  return (
    <div
      className={`prof-field${review ? " needs-review" : ""}${
        conflicts.length ? " has-conflict" : ""
      }${open ? " is-enriching" : ""}`}
    >
      <span className="prof-field-l">{FIELD_LABEL[name] ?? name}</span>
      <span className="prof-field-v">
        {href ? (
          <a className="prof-link" href={href} target="_blank" rel="noreferrer" title={href}>
            {shown}
          </a>
        ) : (
          shown
        )}
      </span>
      <span className="prof-field-meta">
        {showSource && (
          <span className={`src-chip${is_manual ? " src-manual" : ""}`}>
            {source ? <SourceLabel source={source} names={sourceNames} /> : null}
          </span>
        )}
        {freshness && freshness !== "fresh" && (
          <span className={`fresh-dot fresh-${freshness}`}>{freshness}</span>
        )}
        {review && !open && (
          <span className={`prof-review-reason is-${review.reason}`}>
            {REASON_TEXT[review.reason]}
          </span>
        )}
      </span>
      {conflicts.length > 0 && (
        <ul className="conflict-list">
          {conflicts.map((c) => (
            <li key={c.source}>
              <strong>{profilesCompanyProfilePanelConflictingSignal()}</strong> <Msg of={profilesCompanyProfilePanelSays} elems={{ source_label: <SourceLabel source={c.source} names={sourceNames} />, value: <em>{displayValue(name, c.value)}</em> }} />
            </li>
          ))}
        </ul>
      )}
      {open && <FieldReview slug={slug} item={review!} sourceNames={sourceNames} onResolved={onResolved} />}
      {enriching && is_manual && <PinnedField slug={slug} field={name} value={value} onResolved={onResolved} />}
    </div>
  );
}

type SectionSource = CompanyProfileDetail["sources"]["pay"];

/* A part of the profile a plugin answers for every company and has not read for
 * this one: it says so, and never shows RoleBand's own data instead. */
function NotCovered({ source }: { source: SectionSource }) {
  return (
    <div className="empty-hint">
      <Msg of={profilesNotCovered} elems={{ plugin: <Content text={source.plugin_name ?? source.plugin ?? ""} /> }} />
    </div>
  );
}

type LevelBaseRow = CompanyProfileDetail["level_base"][number];

function levelBonus(l: LevelBaseRow): string {
  if (l.bonus_ratio === null || l.bonus_usd === null) return profilesLevelBaseBonus({ choice: "unknown", amount: "", pct: "" });
  if (l.bonus_ratio === 0) return profilesLevelBaseBonus({ choice: "none", amount: "", pct: "" });
  return profilesLevelBaseBonus({ choice: "pct", amount: String(fmtComp(l.bonus_usd)), pct: percent(l.bonus_ratio, 1) });
}

function levelStock(l: LevelBaseRow): ReactNode {
  if (l.stock_usd === null) return <span className="prof-level-evidence">{profilesLevelBaseUnknown()}</span>;
  if (l.stock_usd === 0) return profilesLevelBaseNoStock();
  return fmtComp(l.stock_usd);
}

/** Our data holds stock for this company: some level has a figure. */
const hasStock = (rows: LevelBaseRow[]) => rows.some((l) => l.stock_usd !== null);

/** A rung's amount in the currency the rung was published in. */
const inRungCurrency = (amount: number | null, currency: string) =>
  amount === null ? fmtComp(amount) : fmtCompIn(amount, currency);

/* Our own baseline (atlas `level_base.csv`): estimated base pay per band,
 * the bonus the company's policy states, and stock and a
 * total only where our dataset holds stock. A total needs every part; a level paying less
 * than the one under it is shown and said, never hidden (no evidence floor). */
function OurBaseline({ rows, ladder }: { rows: LevelBaseRow[]; ladder: LevelGuideCompany | undefined }) {
  if (rows.length === 0) {
    return (
      <EmptyState variant="preview" art="rows" title={profilesCompanyProfilePanelNoCompBandsYet()}>
        {profilesLevelBaseNone()}
      </EmptyState>
    );
  }
  const stock = hasStock(rows);
  // The baseline prices the software engineering ladder: the hands-on track's codes.
  const codes = rows.map((l) => levelCode(ladder, l.band, "technical"));
  const coded = codes.some((code) => code !== null);
  return (
    <table className="traj-table prof-comp-table prof-level-base" data-testid="level-base">
      <thead>
        <tr>
          <th scope="col">{profilesCompanyProfilePanelBand()}</th>
          {coded && <th scope="col">{profilesCompanyProfilePanelLevel()}</th>}
          <th scope="col" className="num">{profilesCompanyProfilePanelBase()}</th>
          <th scope="col">{profilesCompanyProfilePanelBonus()}</th>
          {stock && <th scope="col" className="num">{profilesCompanyProfilePanelStock()}</th>}
          {stock && <th scope="col" className="num"><Abbr short={profilesCompanyProfilePanelTotalComp()} full={sharedTcFull()} /></th>}
        </tr>
      </thead>
      <tbody>
        {rows.map((l, index) => (
          <tr key={l.band}>
            <th scope="row">{levelName(l.band)}</th>
            {coded && (
              <td className="traj-ticker">
                {codes[index] ?? <span className="prof-level-evidence">{profilesLevelBaseNoCode({ level: levelName(l.band) })}</span>}
              </td>
            )}
            <td className="num">
              {fmtComp(l.base_usd)}
              {l.below_lower && <span className="prof-level-flag">{profilesLevelBaseBelowLower()}</span>}
            </td>
            <td>{levelBonus(l)}</td>
            {stock && <td className="num">{levelStock(l)}</td>}
            {stock && (
              <td className="num">
                {l.total_usd === null ? <span className="prof-level-evidence">{profilesLevelBaseUnknown()}</span> : fmtComp(l.total_usd)}
              </td>
            )}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// The reusable baseline: what a role at this band actually pays, split into the
// parts that behave differently (cash vs equity).
// A level that arrives without its split, or without a total, is still a
// level: its unknown parts say "Not known", never 0.
function CompBaseline({ profile }: { profile: CompanyProfileDetail }) {
  const mapped = profile.comp_levels
    .filter((l) => l.band)
    .sort((a, b) => BAND_ORDER.indexOf(a.band!) - BAND_ORDER.indexOf(b.band!));

  if (!profile.sources.pay.covered) return <NotCovered source={profile.sources.pay} />;
  if (mapped.length === 0) {
    return (
      <EmptyState variant="preview" art="rows" title={profilesCompanyProfilePanelNoCompBandsYet()}>
        {profilesCompanyProfilePanelNoLevelInThisCompany()}
      </EmptyState>
    );
  }

  return (
    <table className="traj-table prof-comp-table">
      <thead>
        <tr>
          <th scope="col">{profilesCompanyProfilePanelBand()}</th>
          <th scope="col">{profilesCompanyProfilePanelLevel()}</th>
          <th scope="col" className="num"><Abbr short={profilesCompanyProfilePanelTotalComp()} full={sharedTcFull()} /></th>
          <th scope="col">{profilesCompanyProfilePanelComposition()}</th>
          <th scope="col" className="num">{profilesCompanyProfilePanelStock()}</th>
        </tr>
      </thead>
      <tbody>
        {mapped.map((l) => (
          <tr key={l.level_label}>
            <th scope="row">{BAND_LABEL[l.band!] ?? l.band}</th>
            <td className="traj-ticker">{l.level_label}</td>
            <td className="num">{l.tc_median === null ? <span className="prof-level-evidence">{profilesLevelBaseUnknown()}</span> : fmtCompIn(l.tc_median, l.currency)}</td>
            <td>
              {l.base_pct !== null && l.stock_pct !== null && l.bonus_pct !== null && (
                <div
                  className="split-bar"
                  title={profilesCompanyProfilePanelBaseStockBonus({
                    base_usd: String(inRungCurrency(l.base_amount, l.currency)),
                    stock_usd: String(inRungCurrency(l.stock_amount, l.currency)),
                    bonus_usd: String(inRungCurrency(l.bonus_amount, l.currency)),
                  })}
                >
                  <span className="split-base" style={{ width: `${l.base_pct * 100}%` }} />
                  <span className="split-stock" style={{ width: `${l.stock_pct * 100}%` }} />
                  <span className="split-bonus" style={{ width: `${l.bonus_pct * 100}%` }} />
                </div>
              )}
            </td>
            <td className="num">
              {l.stock_pct === null ? <span className="prof-level-evidence">{profilesLevelBaseUnknown()}</span> : percent(l.stock_pct, 0)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** The profile fields that answer "how is an offer built", shown in that card
 *  rather than among identity facts like the ticker and HQ. */
const OFFER_FIELDS = ["equity_vehicle", "vesting_schedule"] as const;

type OfferFact = NonNullable<CompanyProfileDetail["offer_policy"]>["facts"][number];

function offerValue(f: OfferFact): string {
  switch (f.fact) {
    case "equity_rule":
      return profilesOfferEquityRule({ rule: String(f.value) });
    case "bonus_rule":
      return profilesOfferBonusRule({ rule: String(f.value) });
    case "annual_refresh":
      return profilesOfferRefresh({ choice: f.value ? "yes" : "no" });
    case "sign_on_bridges_vesting":
      return profilesOfferSignOn();
    case "base_cap_usd":
      return fmtComp(f.value as number);
  }
}

/* How offers are built: the level atlas's facts about how this company puts
 * pay together, each with who states it, beside the two resolved
 * fields that answer the same question (equity vehicle, vesting). Three
 * answers stay apart: stated, searched and not found, and never
 * researched, which is a card-level sentence rather than a row of dashes. */
function OfferCard({
  data,
  fieldRow,
}: {
  data: CompanyProfileDetail;
  fieldRow: (name: (typeof OFFER_FIELDS)[number], searched: boolean) => ReactNode;
}) {
  const policy = data.offer_policy;
  const unknown = new Set<string>(policy?.unknown_fields ?? []);
  return (
    <div className="panel">
      <div className="prof-card-head">
        <h3>{profilesOfferHeading()}</h3>
        {policy?.verified_on && (
          <span className="prof-card-stat">{profilesOfferChecked({ date: calendarDay(policy.verified_on) })}</span>
        )}
      </div>
      <div className="sub">{policy ? profilesOfferSub() : profilesOfferNotResearched()}</div>
      <div className="prof-fields prof-offer-fields">
        {OFFER_FIELDS.map((name) => fieldRow(name, unknown.has(name)))}
        {(policy?.facts ?? []).map((f) => (
          <div className="prof-field" key={f.fact}>
            <span className="prof-field-l">{profilesOfferFact({ fact: f.fact })}</span>
            <span className={`prof-field-v${f.stated_by ? "" : " is-unknown"}`}>
              {f.stated_by ? offerValue(f) : profilesOfferSearchedNotFound()}
            </span>
            <span className="prof-field-meta">
              {f.stated_by && <span className="src-chip">{sourceName(f.stated_by)}</span>}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

type BenefitItem = CompanyProfileDetail["benefits"][number]["items"][number];

/** A row says something beyond the benefit's name: its words, an estimate, or
 *  how often the company's postings name it. The rest are names only. */
const hasRow = (b: BenefitItem) => Boolean(b.value_text?.trim() || b.value_usd || b.mentions);

function benefitName(b: BenefitItem): ReactNode {
  return b.benefit_type ? profilesBenefitsType({ type: b.benefit_type }) : <Content text={b.name ?? ""} />;
}

/* One benefit, once: its name and tags, any estimate, its best wording under
 * it, how often its postings name it, and its other wordings behind a toggle.
 * Terms lead: an estimate is a partial figure, so it is labelled as one and
 * never stands in for the terms it was computed from. `description` is the
 * longer statement the shown words come from, on hover. */
function BenefitRow({ b }: { b: BenefitItem }) {
  const [open, setOpen] = useState(false);
  const terms = b.value_text?.trim() || null;
  return (
    <li data-kind={b.kind} title={b.description ?? undefined}>
      <span className="benefit-name">
        {benefitName(b)}
        {terms && b.kind === "employer" && <>{" · "}{sourceName("employer")}</>}
        {b.country && <>{" · "}{profilesBenefitsInCountry({ country: country(b.country) })}</>}
      </span>
      {b.value_usd ? (
        <span className="benefit-est">{profilesBenefitsEstimate({ value: fmtComp(b.value_usd) })}</span>
      ) : null}
      {terms && <span className="benefit-terms"><Content text={terms} /></span>}
      {(b.mentions > 0 || b.wordings.length > 0) && (
        <span className="benefit-meta">
          {b.mentions > 0 && profilesBenefitsMentions({ count: b.mentions })}
          {b.mentions > 0 && b.wordings.length > 0 && " · "}
          {b.wordings.length > 0 && (
            <Button variant="link" className="ui-btn-quiet" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
              {profilesBenefitsOtherWordings({ open: open ? "yes" : "no", count: b.wordings.length })}
            </Button>
          )}
        </span>
      )}
      {open && (
        <ul className="benefit-wordings">
          {b.wordings.map((w, index) => (
            <li key={index}>
              <Content text={w.text} />
              {w.kind === "employer" && <>{" · "}{sourceName("employer")}</>}
              {w.country && <>{" · "}{profilesBenefitsInCountry({ country: country(w.country) })}</>}
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

export function CompanyProfilePanel({
  slug,
  enriching = false,
  onResolved,
}: {
  slug: string;
  // The toolbar's Enrich fields mode. Off by default, here as well as on the
  // page: a dossier opens as something to READ.
  enriching?: boolean;
  // Resolving a field changes the company's health badge, so the parent list has
  // to refetch too, or it keeps claiming "2 need review" after they are fixed.
  onResolved?: () => void;
}) {
  const navigate = useNavigate();
  const profile = useAsyncResource<CompanyProfileDetail>(
    () => api.companyProfile(slug), [slug], { keep: "company-profile" });
  // Reference data the Levels tab reads too, kept under its name. Without it
  // the codes stay out; the pay still shows.
  const guide = useAsyncResource<LevelGuide>((signal) => api.levelGuide(signal), [], { keep: "stats/levels" });
  // A switch of source re-reads the whole profile at the one moment it lands:
  // pay, benefits and company size never show two sources.
  useSourceSwitch(profile.refresh);
  const data = profile.data;
  const retryProfile = profile.retry;
  const refreshProfile = profile.refresh;

  // A saved field re-reads the profile in place: the dossier stays on screen
  // while it loads, and a failed re-read is said above it, not in its place.
  const handleResolved = useCallback(() => {
    void refreshProfile({ preserveData: true });
    onResolved?.();
  }, [refreshProfile, onResolved]);

  if (profile.error) {
    return (
      <div className="panel">
        <h2>{profilesCompanyProfilePanelProfileUnavailable()}</h2>
        <div className="empty-hint">{errorText(profile.error)}</div>
        <Button variant="link" onClick={retryProfile}>
          {profilesCompanyProfilePanelRetry()}
        </Button>
      </div>
    );
  }

  if (!data) {
    return (
      <ResourceLoadState error={null} loading={profilesCompanyProfilePanelLoading()} />
    );
  }

  // Countries, not cities: a city count in the hundreds is a number nobody can act on.
  // Unmapped cities count as one bucket, the same way the panel renders them.
  // `?? []` for the same reason the panel below guards with `?.`: a profile
  // whose postings carry no resolvable city may omit the key entirely, and an
  // unguarded read here takes the whole profile down, not just this panel.
  const countryCount = new Set((data.locations ?? []).map((l) => l.country)).size;

  // Whether pay moves with the stock price is our dataset's equity policy,
  // never a level's figures: a pay source may write 0 for stock it does not
  // value (options at a private company), and that 0 does not mean "pays in
  // cash".
  const equityRule = data.offer_policy?.facts.find((f) => f.fact === "equity_rule")?.value;
  const equityPolicy = equityRule === "none" ? "none" : equityRule === "employee_election" ? "election" : null;
  const equitySentence = equityPolicy && (
    <strong data-testid="equity-policy"> {profilesEquityPolicy({ rule: equityPolicy })}</strong>
  );
  const isPublic = Boolean(data.fields.is_public?.value);

  // Review lives in the rows: each flagged field carries its own
  // resolution. Anything flagged that has no rendered field (a reviewable key
  // the profile omits) still gets a row, so no review item can hide.
  const reviewByField = new Map<string, ReviewItem>((data.needs_review ?? []).map((i) => [i.field, i]));
  const extraReviews = (data.needs_review ?? []).filter((i) => !(i.field in data.fields));
  const benefitItems = data.benefits.flatMap((group) => group.items);

  return (
    <div className="prof-detail">
      {profile.refreshError && (
        <div className="empty-hint" role="status">
          {sharedRefreshFailed()}{" "}
          <Button variant="ghost" size="sm" onClick={() => void refreshProfile({ preserveData: true })}>
            {commonTryAgain()}
          </Button>
        </div>
      )}
      <div className="panel">
        <div className="prof-head">
          <div className="prof-identity">
            <CompanyLogo
              slug={slug}
              name={data.display_name}
              logoUrl={data.logo_url}
              brandColor={data.brand_color}
              size={44}
            />
            <div>
              <div className="prof-name-row">
                <h2>{data.display_name}</h2>
                {/* The roles pill holds the badge's slot, so the health signal
                    is a compact dot for anything that still needs review. */}
                {data.data_health !== "ok" && (
                  <span
                    className={`health-dot health-${data.data_health}`}
                    role="img"
                    title={HEALTH_LABEL[data.data_health]}
                    aria-label={HEALTH_LABEL[data.data_health]}
                  />
                )}
              </div>
              <div className="prof-identity-sub">
                {[
                  data.fields.ticker?.value as string | null,
                  data.fields.hq_city?.value as string | null,
                ]
                  .filter(Boolean)
                  .join(" · ") || " "}
              </div>
            </div>
          </div>
          {/* Cross-link into the opportunities module: jump to the board filtered
              to just this company's open roles. */}
          {data.open_roles > 0 ? (
            <button
              type="button"
              className="prof-roles-pill"
              title={profilesCompanyProfilePanelSeeOpenRoles()}
              aria-label={profilesCompanyProfilePanelSeeOpenRolesAt({ count: data.open_roles, open_roles: data.open_roles, display_name: String(data.display_name) })}
              onClick={() => navigate(`/?company=${encodeURIComponent(slug)}`)}
            >
              <Msg of={profilesCompanyProfilePanelOpen} elems={{ open_roles: data.open_roles }} />
            </button>
          ) : data.unfollowed ? (
            // The Board shows followed companies only; say why the
            // jump is missing rather than "0 open", which reads as not hiring.
            <span className="prof-roles-pill is-empty" title={notOnBoardSentence(data.display_name)}>
              {profilesCompanyProfilePanelNotOnYourBoard()}
            </span>
          ) : (
            <span className="prof-roles-pill is-empty">{profilesCompanyProfilePanel0Open()}</span>
          )}
        </div>
        {/* It points at the credit at the foot of the panel, which shows only
            while a plugin answers. */}
        {data.attribution && (
          <div className="sub">
            {profilesCompanyProfilePanelValuesComeFromTheSource()}
          </div>
        )}
        <div className="prof-fields">
          {Object.entries(data.fields)
            .filter(([name]) => !(OFFER_FIELDS as readonly string[]).includes(name))
            .map(([name, field]) => (
            <Field
              key={name}
              name={name}
              field={field}
              review={reviewByField.get(name)}
              enriching={enriching}
              slug={slug}
              sourceNames={data.source_names}
              onResolved={handleResolved}
              notCoveredBy={name === "headcount" && !data.sources.company_size.covered
                ? data.sources.company_size.plugin_name ?? data.sources.company_size.plugin
                : null}
            />
          ))}
          {extraReviews.map((item) => (
            <div
              className={`prof-field needs-review${enriching ? " is-enriching" : ""}`}
              key={item.field}
            >
              <span className="prof-field-l">{FIELD_LABEL[item.field] ?? item.field}</span>
              <span className="prof-field-v">—</span>
              <span className="prof-field-meta">
                {!enriching && (
                  <span className={`prof-review-reason is-${item.reason}`}>
                    {REASON_TEXT[item.reason]}
                  </span>
                )}
              </span>
              {enriching && (
                <FieldReview slug={slug} item={item} sourceNames={data.source_names} onResolved={handleResolved} />
              )}
            </div>
          ))}
        </div>
      </div>

      {(data.locations?.length ?? 0) > 0 && (
        <div className="panel">
          <div className="prof-card-head">
            <h3>{profilesCompanyProfilePanelOfficesOpenRoles()}</h3>
            <span className="prof-card-stat">
              <Msg of={profilesCompanyProfilePanelCountries} args={{ count: countryCount }} elems={{ countryCount: countryCount }} />
            </span>
          </div>
          <div className="sub">
            {profilesCompanyProfilePanelWhereThisCompanyIsHiring()}
          </div>
          <CompanyOffices locations={data.locations} />
        </div>
      )}

      {isPublic && <StockPricePanel slug={slug} ticker={data.fields.ticker?.value as string | null | undefined} />}

      <div className="panel">
        <div className="prof-card-head">
          <h3>{profilesCompanyProfilePanelCompBaseline()}</h3>
          {/* The legend explains the split bars; with no mapped level there
              are no bars, and three colour swatches over an empty state read
              as decoration. */}
          {data.comp_levels.some((l) => l.band && l.tc_median) && (
            <div className="split-legend">
              <span><i className="split-base" /> {profilesCompanyProfilePanelBase()}</span>
              <span><i className="split-stock" /> {profilesCompanyProfilePanelStock()}</span>
              <span><i className="split-bonus" /> {profilesCompanyProfilePanelBonus()}</span>
            </div>
          )}
        </div>
        {/* One source: with no pay plugin selected, our own base per
            level; with one, the plugin's ladder alone. */}
        {data.sources.pay.plugin === null ? (
          <>
            <div className="sub">
              {profilesLevelBaseSub({ stock: hasStock(data.level_base) ? "yes" : "no" })}
              {equitySentence}
            </div>
            <OurBaseline rows={data.level_base} ladder={ladderOf(guide.data, slug)} />
          </>
        ) : (
          <>
            <div className="sub">
              {profilesCompanyProfilePanelWhatARoleAtEach()}
              {equitySentence}
            </div>
            <CompBaseline profile={data} />
          </>
        )}
      </div>

      <OfferCard
        data={data}
        fieldRow={(name, searched) => (
          <Field
            key={name}
            name={name}
            field={data.fields[name]}
            review={reviewByField.get(name)}
            enriching={enriching}
            slug={slug}
            sourceNames={data.source_names}
            onResolved={handleResolved}
            searched={searched}
          />
        )}
      />

      <div className="panel">
        <div className="prof-card-head">
          <h3>{profilesCompanyProfilePanelBenefits()}</h3>
        </div>
        {!data.sources.benefits.covered ? (
          <NotCovered source={data.sources.benefits} />
        ) : benefitItems.length === 0 ? (
          <div className="empty-hint">{profilesBenefitsNotCollected()}</div>
        ) : (
          <>
            {/* What the reader cannot see per row: nothing here is reviewed,
                and a record with no country applies somewhere unrecorded, not
                everywhere (backend/tracker/profiles/benefits_dataset/README.md,
                "an observation"). Each clause shows only while it holds. */}
            {(benefitItems.every((b) => !b.reviewed) || benefitItems.some((b) => !b.country)) && (
              <div className="sub">
                {benefitItems.every((b) => !b.reviewed) && profilesBenefitsUnreviewed()}
                {benefitItems.every((b) => !b.reviewed) && benefitItems.some((b) => !b.country) && " "}
                {benefitItems.some((b) => !b.country) && profilesBenefitsUnscoped()}
              </div>
            )}
            {data.benefits.map((group) => (
              <div className="benefit-group" key={group.category}>
                {/* A taxonomy category; labels the taxonomy does not map sit
                    under `other` by their own names. */}
                <h4>{profilesBenefitsCategory({ category: group.category })}</h4>
                {group.items.some(hasRow) && (
                  <ul className="benefit-list">
                    {group.items.filter(hasRow).map((b, index) => (
                      <BenefitRow key={`${b.provider}:${b.benefit_type ?? b.name}:${index}`} b={b} />
                    ))}
                  </ul>
                )}
                {/* Recorded by name alone: a list, not a row each saying so. */}
                {group.items.some((b) => !hasRow(b)) && (
                  <p className="benefit-also">
                    {profilesBenefitsAlsoListed({
                      names: list(group.items.filter((b) => !hasRow(b)).map((b) =>
                        b.benefit_type ? profilesBenefitsType({ type: b.benefit_type }) : (b.name ?? ""))),
                    })}
                  </p>
                )}
              </div>
            ))}
            {/* A sentence that names several benefits, said once here rather
                than under each benefit it names. */}
            {data.benefit_notes.length > 0 && (
              <div className="benefit-group" data-testid="benefit-notes">
                <h4>{profilesBenefitsShared()}</h4>
                <ul className="benefit-list benefit-notes">
                  {data.benefit_notes.map((note) => (
                    <li key={note.text}>
                      <span className="benefit-terms"><Content text={note.text} /></span>
                      <span className="benefit-meta">{profilesBenefitsMentions({ count: note.mentions })}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </div>

      {/* Only the plugins answering are credited: RoleBand's own data needs none. */}
      {data.attribution && (
        <div className="prof-attribution"><Content text={data.attribution} /></div>
      )}
    </div>
  );
}
