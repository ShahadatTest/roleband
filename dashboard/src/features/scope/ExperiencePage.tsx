import { Link } from "react-router-dom";
import { Badge, Icon } from "../../ui";
import "./ExperiencePage.css";
import {
  profileExperiencePageBackToSummary,
  profileExperiencePageComingSoon,
  profileExperiencePageCvUploadIsnTAvailable,
  profileExperiencePageYourExperience,
} from "../../copy/gen/profile";

/** The CV entry has a real destination; intake is still future work. */
export function ExperiencePage() {
  return (
    <section className="experience-page" aria-labelledby="experience-title">
      <Link to="/profile/direction#summary" className="ui-btn ui-btn-ghost ui-btn-md ui-btn-strong">
        <Icon name="arrowLeft" /> {profileExperiencePageBackToSummary()}
      </Link>
      <div className="experience-page-head">
        <h2 id="experience-title">{profileExperiencePageYourExperience()}</h2>
        <Badge tone="neutral" variant="outline">{profileExperiencePageComingSoon()}</Badge>
      </div>
      <p>{profileExperiencePageCvUploadIsnTAvailable()}</p>
    </section>
  );
}
