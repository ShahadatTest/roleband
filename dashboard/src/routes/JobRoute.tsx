import { useCallback, useEffect } from "react";
import { Navigate, useLocation, useNavigate, useParams } from "react-router-dom";
import { JobDetail } from "../features/job-detail/JobDetail";
import { useJobActions, useJobWorkspace } from "../context/JobWorkspace";
import { positionPath } from "../routing/paths";

/* Routed full-screen detail. Canonical URL nests under the company
   (/company/:slug/job/:id); /job/:id is the short form. Works both as an
   overlay reached from a list and as a standalone page reached by a direct
   link or refresh. Which one is the SLOT's decision (App renders the overlay
   routes separately), not history's: a comparison with a role stacked on it
   carries a background too, and must still render as the page underneath. */
export function JobRoute({ asOverlay = false }: { asOverlay?: boolean }) {
  const { slug, id } = useParams();
  const jobId = Number(id);
  const navigate = useNavigate();
  const location = useLocation();
  const { openJob, openCompare, markJobViewed, setCompare, toggleCompare } = useJobActions();
  // The route subscribes to the selection because the detail's toggle is a
  // STATE, not just a verb: it has to say whether this role is in, and what the
  // selection it is joining already holds.
  const { compareIds, compareFull, compareCap } = useJobWorkspace();

  useEffect(() => {
    if (Number.isInteger(jobId) && jobId > 0) markJobViewed(jobId);
  }, [jobId, markJobViewed]);

  const hasBackground = Boolean((location.state as { backgroundLocation?: unknown } | null)?.backgroundLocation);

  const onBack = useCallback(() => {
    // Reached via in-app navigation: step back so the underlying list keeps its
    // scroll and filters. Reached directly (refresh / shared link): go to board.
    if (hasBackground) navigate(-1);
    else navigate("/");
  }, [hasBackground, navigate]);

  // Canonicalize the URL to the company-scoped form once the job's company is
  // known: a short /job/:id (no slug) or a hand-typed wrong slug is replaced
  // with /company/:slug/job/:id, preserving any overlay background so shared
  // links and the back button keep working.
  const onCompanyResolved = useCallback(
    (companySlug: string) => {
      if (companySlug && slug !== companySlug) {
        navigate(positionPath(companySlug, jobId), { replace: true, state: location.state });
      }
    },
    [slug, jobId, navigate, location.state],
  );

  if (!Number.isInteger(jobId) || jobId <= 0) return <Navigate to="/" replace />;

  return (
    <JobDetail
      jobId={jobId}
      asOverlay={asOverlay}
      onBack={onBack}
      onOpen={openJob}
      onCompare={(ids) => {
        setCompare(ids);
        openCompare();
      }}
      compareOn={compareIds.has(jobId)}
      compareCount={compareIds.size}
      compareDisabled={compareFull}
      compareCap={compareCap}
      onToggleCompare={() => toggleCompare(jobId)}
      onViewCompare={openCompare}
      onCompanyResolved={onCompanyResolved}
    />
  );
}
