import { afterEach, describe, expect, it } from "vitest";
import { activate } from "../../copy/activate";
import { msg } from "../../test/msg";
import { applyAsk } from "./applyAsk";

const form = (over: Partial<Parameters<typeof applyAsk>[0]> = {}) => ({
  required: 9, written: 1, choices: 8, asks_expected_pay: false, read_at: null, ...over,
});

describe("applyAsk", () => {
  it("counts the employer's questions and names the written ones", () => {
    // An employer's form: nine questions, one of them a written "Why us?".
    expect(applyAsk(form())).toBe("9 questions, 1 written answer");
  });

  it("says when the form demands expected pay", () => {
    expect(applyAsk(form({ required: 6, written: 2, asks_expected_pay: true }))).toBe(
      "6 questions, 2 written answers, asks your expected compensation",
    );
  });

  it("does not invent a written answer the form does not ask for", () => {
    expect(applyAsk(form({ required: 1, written: 0, choices: 1 }))).toBe("1 question");
  });

  it("says plainly when there is nothing beyond the resume", () => {
    expect(applyAsk(form({ required: 0, written: 0, choices: 0 }))).toBe("Nothing beyond your resume");
  });
});

describe("applyAsk in the reader's language", () => {
  afterEach(() => activate("en"));

  it("counts questions and written answers with Spanish plurals, no English left", async () => {
    await activate("es");
    expect(applyAsk(form({ required: 1, written: 0 }))).toBe(msg("role-apply-ask-questions", { count: 1 }));
    expect(applyAsk(form())).toBe(
      `${msg("role-apply-ask-questions", { count: 9 })}, ${msg("role-apply-ask-written-answers", { count: 1 })}`,
    );
    expect(applyAsk(form({ required: 6, written: 2 }))).not.toMatch(/question/);
  });
});
