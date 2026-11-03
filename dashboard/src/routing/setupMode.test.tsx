import { act, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../api";
import { profileStateFixture } from "../test/fixtures";
import { useInstallSetUp } from "./installSetUp";
import { forgetSetupProbe, useSetupMode } from "./setupMode";

/* Setup mutes the whole app around Profile, so the one thing it must never do
   is turn on for an install that is already configured. The URL flag only
   asks; the install answers. */

vi.mock("../api", () => ({ api: { profile: vi.fn() } }));
const profile = vi.mocked(api.profile);

function Probe() {
  return <p>mode: {useSetupMode()}</p>;
}

const at = (entry: string) => render(<MemoryRouter initialEntries={[entry]}><Probe /></MemoryRouter>);

beforeEach(() => {
  vi.clearAllMocks();
  forgetSetupProbe();
});

it("is on for a fresh install that asks for it", async () => {
  profile.mockResolvedValue(profileStateFixture({ profile: null, scope_configured: false }));
  at("/profile/direction?setup=1");
  expect(screen.getByText("mode: pending")).toBeInTheDocument();
  expect(await screen.findByText("mode: on")).toBeInTheDocument();
});

it("stays off for a configured install, whatever the URL says", async () => {
  profile.mockResolvedValue(profileStateFixture({ scope_configured: true }));
  at("/profile/direction?setup=1");
  expect(await screen.findByText("mode: off")).toBeInTheDocument();
});

it("stays off when the install cannot be read", async () => {
  profile.mockRejectedValue(new Error("offline"));
  at("/profile/direction?setup=1");
  expect(await screen.findByText("mode: off")).toBeInTheDocument();
});

it("holds the welcome screen for a fresh install, and only then", async () => {
  profile.mockResolvedValue(profileStateFixture({ profile: null, scope_configured: false }));
  at("/welcome");
  expect(await screen.findByText("mode: on")).toBeInTheDocument();
});

it("asks nothing without the flag, or off Profile", async () => {
  profile.mockResolvedValue(profileStateFixture({ profile: null, scope_configured: false }));
  at("/profile/direction");
  expect(screen.getByText("mode: off")).toBeInTheDocument();
  at("/settings?setup=1");
  expect(screen.getAllByText("mode: off")).toHaveLength(2);
  expect(profile).not.toHaveBeenCalled();
});

it("a screen mounted after the install answered reads the answer at once", async () => {
  profile.mockResolvedValue(profileStateFixture({ profile: null, scope_configured: false }));
  const first = at("/welcome");
  expect(await screen.findByText("mode: on")).toBeInTheDocument();
  first.unmount();
  // The walk opens after the welcome: no "pending" frame, so no load state.
  at("/profile/direction?setup=1");
  expect(screen.getByText("mode: on")).toBeInTheDocument();
  expect(profile).toHaveBeenCalledTimes(1);
});

/* A screen that offers the way back into setup must drop the offer once a save
   configures the install, without a reload: the save forgets the probe, and
   the screen asks again. */
it("a screen showing whether the install is set up reads again once the probe is forgotten", async () => {
  function SetUp() {
    const setUp = useInstallSetUp();
    return <p>set up: {setUp === null ? "pending" : String(setUp)}</p>;
  }
  profile.mockResolvedValue(profileStateFixture({ profile: null, scope_configured: false }));
  render(<SetUp />);
  expect(await screen.findByText("set up: false")).toBeInTheDocument();
  profile.mockResolvedValue(profileStateFixture({ profile: null, scope_configured: true }));
  act(() => forgetSetupProbe());
  expect(await screen.findByText("set up: true")).toBeInTheDocument();
  expect(profile).toHaveBeenCalledTimes(2);
});
