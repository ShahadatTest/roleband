import { Badge } from "../../ui";
import {
  profileNewMarkAddedSinceYouLastSaved,
  profileNewMarkNew,
} from "../../copy/gen/profile";

/* A category added since you last saved this setting. It arrives
   switched off; the mark is how you find out it exists at all, and it clears
   the next time the setting is saved. Nothing is new on a setting you never
   saved, so a fresh install shows none. */
export function NewMark({ on }: { on: boolean }) {
  if (!on) return null;
  return (
    <Badge size="sm" tone="info" className="scope-new-mark" title={profileNewMarkAddedSinceYouLastSaved()}>
      {profileNewMarkNew()}
    </Badge>
  );
}
