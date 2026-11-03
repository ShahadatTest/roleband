import { describe, expect, it } from "vitest";
import contract from "../../../launcher/contracts/status-cases.json";
import { estimatesMoving } from "./SyncState";
import { launcherFixture, statusFixture } from "../test/fixtures";

describe("shared launcher presentation", () => {
  for (const value of contract.cases) {
    it(value.name, () => {
      const projection = value.wire as NonNullable<typeof statusFixture.launcher>["status"];
      const status = {
        ...statusFixture, launcher: launcherFixture(projection),
        reference: { ...statusFixture.reference, target_fp: "pending", pending_jobs: 50 },
      };
      // Pending estimates move only while nothing holds the engine back.
      expect(estimatesMoving(status)).toBe(projection.hold === null);
    });
  }
});

describe("estimatesMoving", () => {
  const updating = launcherFixture({ activity: "updating" });
  it("a re-embed alone is not an estimates update", () => {
    const status = { ...statusFixture, launcher: updating, reference: { ...statusFixture.reference, target_fp: null, pending_jobs: 0 } };
    expect(estimatesMoving(status)).toBe(false);
  });
  it("pending rows count only against a target fingerprint", () => {
    const pending = { ...statusFixture.reference, pending_jobs: 12 };
    expect(estimatesMoving({ ...statusFixture, launcher: updating, reference: { ...pending, target_fp: "fp-next" } })).toBe(true);
    expect(estimatesMoving({ ...statusFixture, launcher: updating, reference: { ...pending, target_fp: null } })).toBe(false);
  });
  it("a hold stops it even with pending rows", () => {
    const held = launcherFixture({ hold: { kind: "attention", reason: "schema_pending" } });
    expect(estimatesMoving({ ...statusFixture, launcher: held, reference: { ...statusFixture.reference, target_fp: "fp-next", pending_jobs: 12 } })).toBe(false);
  });
});
