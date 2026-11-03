import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_FILTERS, api } from "./api";

const response = (
  body: unknown,
  status = 200,
  statusText = "OK",
): Response => ({
  ok: status >= 200 && status < 300,
  status,
  statusText,
  json: vi.fn().mockResolvedValue(body),
}) as unknown as Response;

describe("dashboard API client", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => vi.unstubAllGlobals());

  it("passes cancellation through to the jobs transport without changing its query", async () => {
    fetchMock.mockResolvedValue(response({ total: 0, items: [] }));
    const controller = new AbortController();
    await api.jobs({ ...DEFAULT_FILTERS, q: "platform", limit: 1 }, controller.signal);
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("q=platform"), { signal: controller.signal });
    controller.abort();
    expect(fetchMock.mock.calls[0][1].signal.aborted).toBe(true);
  });

  it("serializes repeated filters while omitting only unset values", async () => {
    fetchMock.mockResolvedValue(response({ total: 0, items: [] }));

    await api.jobs({
      ...DEFAULT_FILTERS,
      company: ["openai", "google"],
      q: "",
      base_min: null,
      new_today_only: false,
    });

    const url = new URL(fetchMock.mock.calls[0][0], "https://roleband.test");
    expect(url.searchParams.getAll("company")).toEqual(["openai", "google"]);
    expect(url.searchParams.has("q")).toBe(false);
    expect(url.searchParams.has("base_min")).toBe(false);
    expect(url.searchParams.get("new_today_only")).toBe("false");
  });

  /* `/api/jobs` reads an ABSENT `status` as "open" and an explicit
     `status=` as "no status condition", so an intentionally-empty status must
     survive serialization or Saved and the Board's "All" silently hide closed
     roles. */
  it("sends an explicitly-empty status so 'all statuses' reaches /api/jobs", async () => {
    fetchMock.mockResolvedValue(response({ total: 0, items: [] }));

    await api.jobs({ ...DEFAULT_FILTERS, status: "" });

    const url = new URL(fetchMock.mock.calls[0][0], "https://roleband.test");
    expect(url.searchParams.has("status")).toBe(true);
    expect(url.searchParams.get("status")).toBe("");
    expect(fetchMock.mock.calls[0][0]).toContain("status=");
  });

  it("still sends a chosen status verbatim", async () => {
    fetchMock.mockResolvedValue(response({ total: 0, items: [] }));

    await api.jobs({ ...DEFAULT_FILTERS, status: "closed" });

    const url = new URL(fetchMock.mock.calls[0][0], "https://roleband.test");
    expect(url.searchParams.get("status")).toBe("closed");
  });

  /* The empty-value opt-in is per key for a reason: `viewed` is typed
     `Literal["read","unread"] | None` on the wire, so `viewed=` is a 422 (and
     DEFAULT_FILTERS carries `viewed: ""`, i.e. every board request). A blanket
     allowance would take the whole board down. */
  it("keeps every other empty filter out of the jobs query", async () => {
    fetchMock.mockResolvedValue(response({ total: 0, items: [] }));

    await api.jobs({ ...DEFAULT_FILTERS, status: "", viewed: "", q: "" });

    const url = new URL(fetchMock.mock.calls[0][0], "https://roleband.test");
    expect(url.searchParams.has("viewed")).toBe(false);
    expect(url.searchParams.has("q")).toBe(false);
  });

  /* Same key name, opposite meaning: `/api/lineage/review` validates status
     against pending|confirmed|rejected|reviewed and answers 400 to an empty
     one. The opt-in must not leak out of api.jobs to the shared serializer. */
  it.each([
    ["lineage review", (params: { status?: string }) => api.lineageReview(params)],
    ["twin review", (params: { status?: string }) => api.twinReview(params)],
  ])("omits an empty status for %s, which rejects it", async (_label, request) => {
    fetchMock.mockResolvedValue(response({ total: 0, items: [] }));

    await request({ status: "" });

    const url = new URL(fetchMock.mock.calls[0][0], "https://roleband.test");
    expect(url.searchParams.has("status")).toBe(false);
  });

  it("uses JSON request bodies consistently for write verbs", async () => {
    fetchMock.mockResolvedValue(response({ slug: "openai" }));

    await api.addCompany({ catalog_slug: "openai" });

    expect(fetchMock).toHaveBeenCalledWith("/api/companies", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ catalog_slug: "openai" }),
    });
  });

  it.each([
    ["GET", () => api.facets()],
    ["PUT", () => api.setIntelligenceEnabled(true)],
    ["POST", () => api.sync()],
    ["PATCH", () => api.updateCompany("openai", { enabled: false })],
    ["DELETE", () => api.removePriceFeedKey()],
    ["favorite", () => api.setFavorite(101, true)],
  ])("surfaces backend detail errors for %s requests", async (_label, request) => {
    fetchMock.mockResolvedValue(response({ detail: "Action rejected by policy" }, 409, "Conflict"));

    await expect(request()).rejects.toThrow("Action rejected by policy");
  });

  it("falls back to the HTTP status when an error response is not JSON", async () => {
    const res = response(null, 503, "Service Unavailable");
    vi.mocked(res.json).mockRejectedValue(new SyntaxError("not JSON"));
    fetchMock.mockResolvedValue(res);

    await expect(api.status()).rejects.toThrow("503 Service Unavailable");
  });

  it("routes favorite changes through the shared request contract", async () => {
    fetchMock.mockResolvedValue(response({ job_id: 101, is_favorite: true }));

    await api.setFavorite(101, true);

    expect(fetchMock).toHaveBeenCalledWith("/api/jobs/101/favorite", { method: "PUT" });
  });

  it("marks an opened opportunity through an idempotent POST", async () => {
    fetchMock.mockResolvedValue(response({ job_id: 101, viewed_at: "2026-07-15T18:30:00Z" }));

    await api.markJobViewed(101);

    expect(fetchMock).toHaveBeenCalledWith("/api/jobs/101/view", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
  });
});

describe("Insights scope in a request", () => {
  it("leaves an unscoped request the plain route and adds only what narrows", async () => {
    const { scoped } = await import("./api/statistics");
    expect(scoped("/api/demand")).toBe("/api/demand");
    expect(scoped("/api/demand", { side: "all", families: [] })).toBe("/api/demand");
    expect(scoped("/api/demand", { side: "other", families: [] })).toBe("/api/demand?side=other");
    expect(scoped("/api/statistics/velocity?days=30", { side: "yours", families: ["product_management", "design_ux"] }))
      .toBe("/api/statistics/velocity?days=30&side=yours&family=product_management&family=design_ux");
  });
});
