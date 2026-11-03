import type { JobDetail } from "../../api";
import {
  roleApplyAskAsksYourExpectedPay,
  roleApplyAskNothingBeyondYourResume,
  roleApplyAskQuestions,
  roleApplyAskWrittenAnswers,
} from "../../copy/gen/role";

type Form = NonNullable<JobDetail["application_form"]>;

/** What applying asks beyond name, contact and resume, in one line.
 *  Read from the posting's own page, and counts only: the questions' wording
 *  is never stored. */
export function applyAsk(form: Form): string {
  if (form.required === 0) return roleApplyAskNothingBeyondYourResume();
  const parts = [roleApplyAskQuestions({ count: form.required })];
  if (form.written > 0) parts.push(roleApplyAskWrittenAnswers({ count: form.written }));
  if (form.asks_expected_pay) parts.push(roleApplyAskAsksYourExpectedPay());
  return parts.join(", ");
}
