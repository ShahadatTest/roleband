import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../../api";
import { ApiError } from "../../api/transport";
import { usageStateFixture } from "../../test/fixtures";
import { ConsentPane } from "./ConsentPane";
import { consentText, consentWords, groupsToAsk } from "./consentCopy";

/* The usage-sharing question (docs/architecture.md): the record carries
   exactly the words on screen, "Happy to help" shares every kind asked in one
   click, nothing is ever pre-ticked, choosing shares exactly what was ticked,
   and a refusal says so and shares nothing. */

vi.mock("../../api", () => ({
  api: { saveUsageConsent: vi.fn() },
}));

const ALL = ["usage", "crashes", "questions"] as const;

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.saveUsageConsent).mockResolvedValue(usageStateFixture("shared"));
});

function sent() {
  expect(api.saveUsageConsent).toHaveBeenCalledTimes(1);
  return vi.mocked(api.saveUsageConsent).mock.calls[0][0];
}

const region = () => screen.getByRole("region", { name: "Help us improve" });
const answerNames = () => within(region()).getAllByRole("button").map((button) => button.textContent);

it("records exactly the words the screen shows", async () => {
  render(<ConsentPane state={usageStateFixture("undecided")} groups={[...ALL]} onAnswered={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: "Happy to help" }));
  await waitFor(() => expect(api.saveUsageConsent).toHaveBeenCalled());
  const { text, locale } = sent();
  expect(text).toBe(consentText(consentWords([...ALL])));
  for (const paragraph of text.split("\n\n")) {
    for (const part of paragraph.split(": ")) expect(region()).toHaveTextContent(part.trim());
  }
  expect(locale).toBe("en");
});

it("the welcome's look records the same words, keeps the answers equal, and puts a box in each icon's place", async () => {
  const { container } = render(<ConsentPane look="scene" state={usageStateFixture("undecided")} groups={[...ALL]} onAnswered={vi.fn()} />);
  // One mark for each kind, and one for the promise; no box until someone chooses.
  expect(container.querySelectorAll(".privacy-consent-icon")).toHaveLength(4);
  expect(screen.queryByRole("checkbox")).toBeNull();
  const no = screen.getByRole("button", { name: "No thanks" });
  expect(no.className).toBe(screen.getByRole("button", { name: "Happy to help" }).className);

  await userEvent.click(screen.getByRole("button", { name: "Let me choose" }));
  expect(screen.getAllByRole("checkbox")).toHaveLength(3);
  expect(container.querySelectorAll(".privacy-consent-choice .privacy-consent-icon")).toHaveLength(0);
  await userEvent.click(screen.getByRole("checkbox", { name: /Crash reports/ }));
  await userEvent.click(screen.getByRole("button", { name: "Happy to help" }));
  await waitFor(() => expect(api.saveUsageConsent).toHaveBeenCalled());
  const { text, answers } = sent();
  expect(text).toBe(consentText(consentWords([...ALL])));
  expect(answers).toEqual({ usage: false, crashes: true, questions: false });
});

it("speaks as us, gives a reason to help, and says what is never sent", () => {
  render(<ConsentPane state={usageStateFixture("undecided")} groups={[...ALL]} onAnswered={vi.fn()} />);
  expect(screen.getByRole("heading", { name: "Help us improve" })).toBeVisible();
  expect(region()).toHaveAccessibleDescription(/free and open source/);
  // The product's name is not spent where "us" will do.
  expect(region()).not.toHaveTextContent("RoleBand");
  for (const name of ["Anonymous usage data", "Crash reports", "Feedback surveys"]) {
    expect(within(region()).getByText(name)).toBeVisible();
  }
  expect(region()).toHaveTextContent("Never sent: company names, role titles, compensation, your CV or anything you type.");
  expect(region()).not.toHaveTextContent(/Where it goes|PostHog|Session recordings/);
});

it("asks with nothing ticked: no box until someone chooses", () => {
  render(<ConsentPane state={usageStateFixture("undecided")} groups={[...ALL]} onAnswered={vi.fn()} />);
  expect(screen.queryByRole("checkbox")).toBeNull();
  expect(answerNames()).toEqual(["Let me choose", "No thanks", "Happy to help"]);
});

it("Happy to help shares every kind asked, in one click", async () => {
  render(<ConsentPane state={usageStateFixture("undecided")} groups={[...ALL]} onAnswered={vi.fn()} />);
  const no = screen.getByRole("button", { name: "No thanks" });
  const yes = screen.getByRole("button", { name: "Happy to help" });
  expect(no.className).toBe(yes.className);
  await userEvent.click(yes);
  await waitFor(() => expect(api.saveUsageConsent).toHaveBeenCalled());
  const { answers, fingerprints } = sent();
  expect(answers).toEqual({ usage: true, crashes: true, questions: true });
  expect(fingerprints).toEqual({
    usage: "usage-fingerprint", crashes: "crashes-fingerprint", questions: "questions-fingerprint",
  });
});

it("choosing opens clear boxes, focuses the first, and shares exactly what was ticked", async () => {
  render(<ConsentPane state={usageStateFixture("undecided")} groups={[...ALL]} onAnswered={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: "Let me choose" }));
  const boxes = screen.getAllByRole("checkbox");
  expect(boxes).toHaveLength(3);
  for (const box of boxes) expect(box).not.toBeChecked();
  expect(boxes[0]).toHaveFocus();
  expect(screen.queryByRole("button", { name: "Let me choose" })).toBeNull();
  // Nothing ticked is nothing to share: the warm answer waits.
  expect(screen.getByRole("button", { name: "Happy to help" })).toBeDisabled();
  // The whole row is the hit target.
  await userEvent.click(screen.getByText("What broke and where, so we can fix it fast."));
  await userEvent.click(screen.getByRole("button", { name: "Happy to help" }));
  await waitFor(() => expect(api.saveUsageConsent).toHaveBeenCalled());
  expect(sent().answers).toEqual({ usage: false, crashes: true, questions: false });
});

it("No thanks declines everything, even with boxes ticked", async () => {
  const onAnswered = vi.fn();
  render(<ConsentPane state={usageStateFixture("undecided")} groups={[...ALL]} onAnswered={onAnswered} />);
  await userEvent.click(screen.getByRole("button", { name: "Let me choose" }));
  await userEvent.click(screen.getByRole("checkbox", { name: /Anonymous usage data/ }));
  await userEvent.click(screen.getByRole("button", { name: "No thanks" }));
  await waitFor(() => expect(onAnswered).toHaveBeenCalled());
  expect(sent().answers).toEqual({ usage: false, crashes: false, questions: false });
});

it("asks about one kind with nothing to choose, and declines only it", async () => {
  const onAnswered = vi.fn();
  render(<ConsentPane state={usageStateFixture("undecided")} groups={["questions"]} onAnswered={onAnswered} />);
  expect(screen.queryByText("Anonymous usage data")).toBeNull();
  expect(answerNames()).toEqual(["No thanks", "Happy to help"]);
  await userEvent.click(screen.getByRole("button", { name: "No thanks" }));
  await waitFor(() => expect(onAnswered).toHaveBeenCalled());
  expect(sent().answers).toEqual({ questions: false });
  expect(sent().text).not.toContain("Anonymous usage data");
});

it("says why when the answer is refused, and stays on the question", async () => {
  vi.mocked(api.saveUsageConsent).mockRejectedValue(
    new ApiError("older scope", 409, "usage-catalogue-changed", { groups: ["usage"] }),
  );
  const onAnswered = vi.fn();
  render(<ConsentPane state={usageStateFixture("undecided")} groups={[...ALL]} onAnswered={onAnswered} />);
  await userEvent.click(screen.getByRole("button", { name: "Happy to help" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("What's shared changed while you were choosing. Try again.");
  expect(onAnswered).not.toHaveBeenCalled();
});

it("asks only about groups never answered or widened since", () => {
  const state = usageStateFixture("declined");
  state.groups[0].status = "undecided";
  state.groups[1].status = "stale";
  state.groups[2].status = "shared";
  expect(groupsToAsk(state)).toEqual(["usage", "crashes"]);
});
