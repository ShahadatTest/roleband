import type { CompanyDiscoveryCompany } from "../../api";
import {
  companiesConnectorActive,
  companiesConnectorFamily,
  companiesConnectorLive,
  companiesConnectorParked,
  companiesConnectorPlanned,
  companiesModelReadyToEnable,
  companiesParkedBotProtected,
  companiesParkedProhibitsCollection,
  companiesParkedRobotsDisallow,
} from "../../copy/gen/companies";

type State = CompanyDiscoveryCompany["connector_state"];
type Parked = NonNullable<CompanyDiscoveryCompany["parked_reason"]>;

/* A company's connector in words: the server sends its state and,
 * for a parked company, why. A `Record` over the API's own codes, so a state
 * or reason the backend adds without a message here is a type error. */
const STATE: Record<State, () => string> = {
  live: companiesConnectorLive,
  ready: companiesModelReadyToEnable,
  family: companiesConnectorFamily,
  active: companiesConnectorActive,
  planned: companiesConnectorPlanned,
  parked: companiesConnectorParked,
};

const PARKED: Record<Parked, (company: string) => string> = {
  bot_protected: () => companiesParkedBotProtected(),
  robots_disallow: (company) => companiesParkedRobotsDisallow({ company }),
  prohibits_collection: () => companiesParkedProhibitsCollection(),
};

export function connectorText(company: Pick<CompanyDiscoveryCompany, "display" | "connector_state" | "parked_reason">): string {
  return company.parked_reason ? PARKED[company.parked_reason](company.display) : STATE[company.connector_state]();
}
