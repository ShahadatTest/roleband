import { ProfileView } from "../features/scope/ProfileView";
import { SetupCompanies } from "../features/companies/SetupCompanies";

/* Profile, composed here rather than in `features/scope/` because first-run
   setup's last step belongs to another feature: which companies the radar
   scans is Companies' question, asked inside Profile's walk. */
export function ProfileRoute() {
  return <ProfileView setupCompanies={(props) => <SetupCompanies {...props} />} />;
}
