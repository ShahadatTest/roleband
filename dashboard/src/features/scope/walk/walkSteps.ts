import {
  profilePersonaRailLevel,
  profileSummaryStepInterests,
  profileSummaryStepRole,
  profileSummaryStepWhere,
  profileSummaryStepWhichRoles,
  profileWalkStepsAnyParticularRoles,
  profileWalkStepsAnythingYouCareAboutOr,
  profileWalkStepsEveryRoleOfEachKind,
  profileWalkStepsParticularRolesOrAnyThat,
  profileWalkStepsPickOneOrMore,
  profileWalkStepsTheFieldsAndIndustriesThe,
  profileWalkStepsTheKindOfWorkYou,
  profileWalkStepsTodayAndTheOneYou,
  profileWalkStepsTopicsToLookForAnd,
  profileWalkStepsWhatKindOfRoleAre,
  profileWalkStepsWhereDoYouWantTo,
  profileWalkStepsWhereYouAreTodayUp,
  profileWalkStepsWhereYouReBasedAnd,
  profileWalkStepsYourBasesAndHowFar,
  profileWalkStepsYourLevel,
} from "../../../copy/gen/profile";
/* The walk's steps: ids, the tab labels, and each question's title and note.
   Its own module so the walk and the rail read it without importing the walk.
   */

export type StepId = "accountable" | "level" | "where" | "roles" | "subjects";
/** `companies` is first-run setup's last step only (routing/setupMode.ts). */
export type WalkView = StepId | "summary" | "companies";

/** `gist`: what the step decides, in one line. The guide and the radar
    pyramid both say it, from here. */
export const STEPS: readonly { id: StepId; label: string; optional: boolean; title: string; note: string; gist: string }[] = [
  {
    id: "accountable", get label() { return profileSummaryStepRole(); }, optional: false,
    get title() { return profileWalkStepsWhatKindOfRoleAre(); },
    get note() { return profileWalkStepsPickOneOrMore(); },
    get gist() { return profileWalkStepsTheKindOfWorkYou(); },
  },
  {
    id: "level", get label() { return profilePersonaRailLevel(); }, optional: false,
    get title() { return profileWalkStepsYourLevel(); },
    get note() { return profileWalkStepsTodayAndTheOneYou(); },
    get gist() { return profileWalkStepsWhereYouAreTodayUp(); },
  },
  {
    id: "where", get label() { return profileSummaryStepWhere(); }, optional: false,
    get title() { return profileWalkStepsWhereDoYouWantTo(); },
    get note() { return profileWalkStepsWhereYouReBasedAnd(); },
    get gist() { return profileWalkStepsYourBasesAndHowFar(); },
  },
  {
    id: "roles", get label() { return profileSummaryStepWhichRoles(); }, optional: true,
    get title() { return profileWalkStepsAnyParticularRoles(); },
    get note() { return profileWalkStepsEveryRoleOfEachKind(); },
    get gist() { return profileWalkStepsParticularRolesOrAnyThat(); },
  },
  {
    id: "subjects", get label() { return profileSummaryStepInterests(); }, optional: true,
    get title() { return profileWalkStepsAnythingYouCareAboutOr(); },
    get note() { return profileWalkStepsTheFieldsAndIndustriesThe(); },
    get gist() { return profileWalkStepsTopicsToLookForAnd(); },
  },
];
