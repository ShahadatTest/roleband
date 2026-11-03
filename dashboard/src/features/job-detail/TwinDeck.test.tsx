import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../api";
import type { TwinDetail } from "../../api";
import { jobDetailRowFixture, twinProposalFixture } from "../../test/fixtures";
import { TwinDeck } from "./TwinDeck";

vi.mock("../../api", () => ({ api: { twins: vi.fn() } }));

describe("TwinDeck", () => {
  beforeEach(() => vi.clearAllMocks());

  it("reveals direct twins and sends the whole pair to Compare", async () => {
    // Complete as `GET /api/jobs/{id}/twins` sends it: only the direct twin carries its link.
    const detail: TwinDetail = {
      job_id: 1,
      size: 3,
      direct_count: 1,
      members: [
        { job: jobDetailRowFixture({ id: 1, req_id: "A" }), direct: false, link: null },
        {
          job: jobDetailRowFixture({ id: 2, req_id: "B", title: "Staff Security Architect" }),
          direct: true,
          link: twinProposalFixture({ id: 31, job_id: 2, prior_job_id: 1, method: "manual", status: "confirmed", decision: "twin" }),
        },
        { job: jobDetailRowFixture({ id: 3, req_id: "C" }), direct: false, link: null },
      ],
    };
    vi.mocked(api.twins).mockResolvedValue(detail);
    const onCompare = vi.fn();
    render(<TwinDeck jobId={1} onOpen={vi.fn()} onCompare={onCompare} />);

    await userEvent.click(await screen.findByRole("button", { name: /Has a related role/ }));
    expect(screen.getByText("Staff Security Architect")).toBeInTheDocument();
    expect(screen.getByText(/req C/)).toBeInTheDocument();
    expect(screen.getByText(/not directly related/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Compare with related roles" }));
    expect(onCompare).toHaveBeenCalledWith([1, 2]);
  });
});
