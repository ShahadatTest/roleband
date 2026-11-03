import { JobWorkspaceProvider } from "./JobWorkspace";
import { MissionStateProvider } from "./MissionState";
import { SyncStateProvider } from "./SyncState";

/**
 * The three app contexts, composed once.
 *
 * Order is a real dependency, not a style: `SyncState` reads `refreshStats`
 * from `MissionState`, because the running -> idle edge of a scrape is exactly
 * when the header counts change.
 *
 * `JobWorkspace` depends on neither and sits innermost, closest to the dense
 * surfaces that consume it.
 */
export function AppProviders({ children }: { children: React.ReactNode }) {
  return (
    <MissionStateProvider>
      <SyncStateProvider>
        <JobWorkspaceProvider>{children}</JobWorkspaceProvider>
      </SyncStateProvider>
    </MissionStateProvider>
  );
}
