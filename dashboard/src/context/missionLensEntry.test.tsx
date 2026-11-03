import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { shellApi } from "../api/shell";
import { statsFixture } from "../test/fixtures";
import { MissionStateProvider, useMissionState } from "./MissionState";

vi.mock("../api/shell", () => ({ shellApi: { stats: vi.fn() } }));

beforeEach(() => {
  vi.mocked(shellApi.stats).mockResolvedValue(statsFixture);
});

function Probe() {
  const { newSignalsOnly, repostsOnly } = useMissionState();
  const location = useLocation();
  return (
    <output data-testid="probe">
      {`${location.pathname}${location.search}|new=${newSignalsOnly}|reposts=${repostsOnly}`}
    </output>
  );
}

function open(address: string) {
  render(
    <MemoryRouter initialEntries={[address]}>
      <MissionStateProvider>
        <Probe />
      </MissionStateProvider>
    </MemoryRouter>,
  );
  return screen.getByTestId("probe");
}

describe("the board's New entry address", () => {
  it("opens the board on New and leaves the address clean", async () => {
    const probe = open("/?lens=new");
    await waitFor(() => expect(probe).toHaveTextContent("/|new=true|reposts=false"));
  });

  it("keeps the board's other parameters", async () => {
    const probe = open("/?show=closed&lens=new&company=stripe");
    await waitFor(() => expect(probe).toHaveTextContent("/?show=closed&company=stripe|new=true"));
  });

  it("ignores any other lens value, and leaves it in the address", async () => {
    const probe = open("/?lens=reposts");
    await waitFor(() => expect(shellApi.stats).toHaveBeenCalled());
    expect(probe).toHaveTextContent("/?lens=reposts|new=false|reposts=false");
  });

  it("narrows nothing off the board", async () => {
    const probe = open("/settings?lens=new");
    await waitFor(() => expect(shellApi.stats).toHaveBeenCalled());
    expect(probe).toHaveTextContent("/settings?lens=new|new=false");
  });

  it("a plain board address stays open", async () => {
    const probe = open("/");
    await waitFor(() => expect(shellApi.stats).toHaveBeenCalled());
    expect(probe).toHaveTextContent("/|new=false|reposts=false");
  });
});
