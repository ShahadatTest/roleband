import { ReviewScreen } from "../features/review/ReviewScreen";
import { PageHeader } from "../patterns/PageHeader";
import {
} from "../copy/gen/duplicates";
import { shellNavDuplicates } from "../copy/gen/shell";

export function ReviewRoute() {
  return (
    <main className="main review-main" data-design-system="app">
      <PageHeader title={shellNavDuplicates()} />
      <ReviewScreen />
    </main>
  );
}
