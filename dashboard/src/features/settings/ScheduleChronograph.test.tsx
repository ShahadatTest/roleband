import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, describe, expect, it, vi } from "vitest";
import type { SyncSchedule } from "../../api";
import { schedulePlanFixture } from "../../test/fixtures";
import { useWriteQueue } from "../../hooks/useWriteQueue";
import { ScheduleChronograph } from "./ScheduleChronograph";
import type { ScheduleMove } from "./useDialDrag";
import { reconciliationWindow, scheduleClusters, scheduleChartSummary } from "./charts/schedule";

/* The dial's interaction contracts, rendered.
 *
 * `ScheduleSection.test.tsx` covers what the dial DRAWS and the one happy-path
 * commit. These are the four it does not reach, and they are the four a
 * decomposition can break silently because each lives in a ref, a portal or a
 * catch: Escape closing the inspector (ui/Overlay's contract, not ours), the
 * marks being reachable by keyboard at all, a cancelled drag putting the
 * marker back, and a rejected save keeping the last good time on screen
 * instead of the one that failed to persist.
 */

/* jsdom implements NO pointer capture: `setPointerCapture` is not a function.
 * Stubbing the browser API jsdom lacks lets a drag run the path it runs in a
 * browser, through to the commit; the subject is untouched. */
beforeAll(() => {
  Element.prototype.setPointerCapture = function setPointerCapture() {};
  Element.prototype.releasePointerCapture = function releasePointerCapture() {};
});

const binding = (over: Partial<SyncSchedule["bindings"][number]> = {}): SyncSchedule["bindings"][number] => ({
  binding_id: 1,
  company: "openai",
  provider: "greenhouse",
  closure_capability: "authoritative",
  scheduled: true,
  discovery_enabled: true,
  discovery_cadence_seconds: 21_600,
  reconcile_cadence_seconds: 86_400,
  last_discovery_at: null,
  last_reconcile_at: null,
  next_discovery_at: "2026-07-28T16:00:00Z",
  next_reconcile_at: "2026-07-28T20:00:00Z",
  discovery_anchor_minute: null,
  reconcile_anchor_minute: null,
  schedule_timezone: null,
  eligible_discovery_at: "2026-07-28T16:00:00Z",
  eligible_reconcile_at: "2026-07-28T20:00:00Z",
  manual_requested_at: null,
  last_outcome: "ok",
  last_new_count: 1,
  consecutive_empty_discoveries: 0,
  provider_state: "ready",
  cooldown_until: null,
  status: "scheduled",
  waits_for_user: null,
  ...over,
});

const schedule = (): SyncSchedule => ({
  generated_at: "2026-07-28T14:30:00Z",
  enabled: true,
  tick_seconds: 600,
  max_parallel_providers: 2,
  authoritative_stale_hours: 30,
  // The per-company timers: the dial these tests were written for.
  plan: schedulePlanFixture({ enabled: false }),
  providers: [{
    provider: "greenhouse", state: "ready", cooldown_until: null,
    last_started_at: null, last_finished_at: null, last_outcome: "ok", binding_count: 1,
  }],
  bindings: [binding()],
});

/* Wired as ScheduleSection wires it: every write through one queue, and the
   queue's busy state handed back to the dial. */
function Wired({ onMove }: { onMove: (move: ScheduleMove) => Promise<void> }) {
  const data = schedule();
  const { exclusive, writing } = useWriteQueue("schedule");
  return (
    <ScheduleChronograph
      schedule={data}
      clusters={scheduleClusters(data)}
      window={reconciliationWindow(data)}
      summary={scheduleChartSummary(data)}
      busy={writing}
      onMove={(move) => exclusive([], () => onMove(move))}
      onPlan={() => exclusive([], async () => undefined)}
    />
  );
}

function mount(onMove = vi.fn().mockResolvedValue(undefined)) {
  const view = render(<Wired onMove={onMove} />);
  return { view, onMove };
}

/** The dial's marks are the buttons that name a move. */
const marks = () => screen.getAllByRole("button", { name: /^Move / });

describe("the chronograph's interaction contracts", () => {
  it("reaches every mark by keyboard", async () => {
    /* The stage cancels mousedown so a drag cannot start a text selection,
       which is the reason this file carries an a11y allowance. The allowance
       is for a DIV that is not a click target — it must never become an
       excuse for the marks themselves being unreachable. */
    mount();
    const user = userEvent.setup();
    const all = marks();
    expect(all.length).toBeGreaterThan(0);

    for (const mark of all) expect(mark).toBeEnabled();
    await user.tab();
    let guard = 0;
    while (!all.includes(document.activeElement as HTMLButtonElement) && guard++ < 20) {
      await user.tab();
    }
    expect(
      all.includes(document.activeElement as HTMLButtonElement),
      "no mark could be reached with Tab",
    ).toBe(true);
  });

  it("closes the inspector on Escape, and releases the mark it lit", async () => {
    const user = userEvent.setup();
    mount();
    await user.click(marks()[0]);
    const field = await screen.findByLabelText(/time$/);
    expect(field).toBeInTheDocument();

    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByLabelText(/time$/)).not.toBeInTheDocument());
    // The ring is the dial's statement that this mark is in hand; it ends with
    // the inspector or every mark ever opened stays lit.
    for (const mark of marks()) expect(mark.className).not.toContain("selected");
  });

  it("puts the marker back when a drag is cancelled", async () => {
    const { onMove } = mount();
    const mark = marks()[0];
    const resting = mark.style.left;

    fireEvent.pointerDown(mark, { pointerId: 1, clientX: 100, clientY: 100 });
    fireEvent.pointerMove(mark, { pointerId: 1, clientX: 180, clientY: 40 });
    // The drag is live: the marker has left its persisted position. Moves land
    // on the next animation frame (one render per frame, not per pointer report).
    await waitFor(() => expect(mark.style.left, "the drag never moved the marker").not.toBe(resting));

    fireEvent.pointerCancel(mark, { pointerId: 1 });

    // A cancelled drag is not a reschedule, and the marker may not be left
    // sitting at a time nothing is going to save.
    await waitFor(() => expect(mark.style.left).toBe(resting));
    expect(onMove).not.toHaveBeenCalled();
    expect(screen.getByRole("status").textContent).not.toMatch(/Saving/);
  });

  it("hands the dial back to the schedule once a save settles", async () => {
    /* The drag draft is the dial's only local truth, and it must not outlive
       the request: afterwards the marker reads from the schedule prop again,
       which is what lets the parent's refetch be the single source. With a
       static prop that means it snaps back to the stored time — visibly
       wrong-looking in a test, exactly right as a rule. */
    const { onMove } = mount();
    const mark = marks()[0];
    const resting = mark.style.left;

    fireEvent.pointerDown(mark, { pointerId: 1, clientX: 100, clientY: 100 });
    fireEvent.pointerMove(mark, { pointerId: 1, clientX: 180, clientY: 40 });
    fireEvent.pointerUp(mark, { pointerId: 1, clientX: 180, clientY: 40 });

    await waitFor(() => expect(onMove).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(mark.style.left).toBe(resting));
  });

  it("ignores the click that ends a drag, and opens on the next real one", async () => {
    /* A drag ends in a click — the browser sends both — and that click must
       not also open the inspector over the dial.

       TWO things stop it, which is worth knowing before touching either. The
       mark is `disabled` while its write is in flight, so the DOM drops the
       click; and `suppressClickRef` latches in finishDrag, to be consumed by
       the click that follows. The disabled state gets there first, which
       makes the latch unobservable from the UI: this suite cannot hold it. It
       is kept as the guard for a moved drag that does NOT persist, and
       because `startDrag` clears it at the start of the next interaction,
       which is what makes the click below work at all. */
    const user = userEvent.setup();
    const { onMove } = mount();
    const mark = marks()[0];

    fireEvent.pointerDown(mark, { pointerId: 1, clientX: 100, clientY: 100 });
    fireEvent.pointerMove(mark, { pointerId: 1, clientX: 180, clientY: 40 });
    fireEvent.pointerUp(mark, { pointerId: 1, clientX: 180, clientY: 40 });
    fireEvent.click(mark);

    await waitFor(() => expect(onMove).toHaveBeenCalledTimes(1));
    expect(
      screen.queryByLabelText(/time$/),
      "the click that ended the drag also opened the inspector",
    ).not.toBeInTheDocument();

    // A real click — pointerdown first, which is what releases the latch.
    await waitFor(() => expect(marks()[0]).toBeEnabled());
    await user.click(marks()[0]);
    expect(await screen.findByLabelText(/time$/)).toBeInTheDocument();
  });

  it("persists the move even when releasing the pointer capture throws", async () => {
    /* `releasePointerCapture` is specified to raise NotFoundError for a
       pointerId the browser does not count as active, and it is called in
       the pointerup handler, the exact moment a pointer stops being active,
       before the persist call. Unguarded, one throw would drop the write the
       drag exists to make: no error, the marker snaps back, the schedule is
       simply unchanged.

       This is the one half of pointer capture a component test can hold. The
       capture itself cannot be tested here at all — jsdom implements neither
       method, and the stub above is what lets these drags reach a commit in
       the first place. What holds THAT is tests/ux/schedule.spec.ts, in a real
       browser: remove the two capture calls and its two mouse drags fail,
       because the pointer leaves the 24px mark and the events stop arriving. */
    const release = vi
      .spyOn(Element.prototype, "releasePointerCapture")
      .mockImplementation(() => {
        throw new DOMException("no active pointer", "NotFoundError");
      });
    try {
      const { onMove } = mount();
      const mark = marks()[0];

      fireEvent.pointerDown(mark, { pointerId: 1, clientX: 100, clientY: 100 });
      fireEvent.pointerMove(mark, { pointerId: 1, clientX: 180, clientY: 40 });
      fireEvent.pointerUp(mark, { pointerId: 1, clientX: 180, clientY: 40 });

      await waitFor(() => expect(onMove).toHaveBeenCalledTimes(1));
    } finally {
      release.mockRestore();
    }
  });

  it("keeps the last good time on screen when the save is rejected", async () => {
    /* The field is controlled from the persisted schedule, so a rejected save
       must leave it reading the time that IS stored — not the one the user
       tried. The error says what happened; the dial must not imply the move
       landed. */
    const onMove = vi.fn().mockRejectedValue(new Error("Schedule update failed."));
    const user = userEvent.setup();
    mount(onMove);

    await user.click(marks()[0]);
    const field = await screen.findByLabelText(/time$/) as HTMLInputElement;
    const stored = field.value;

    await user.clear(field);
    await user.type(field, "03:30");
    await user.keyboard("{Enter}");

    await waitFor(() => expect(onMove).toHaveBeenCalledTimes(1));
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't move that scan. Try again.");
    await waitFor(() => expect(field.value).toBe(stored));
  });
});
