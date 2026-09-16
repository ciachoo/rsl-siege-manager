import { screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import type { SiegeScannerEvidenceResponse } from "../../api/types";
import { ScannerEvidencePanel } from "../../components/ScannerEvidencePanel";
import { server } from "../server";
import { renderWithProviders } from "../utils";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function evidenceResponse(
  overrides: Partial<SiegeScannerEvidenceResponse> = {}
): SiegeScannerEvidenceResponse {
  return {
    siege_id: 42,
    has_evidence: true,
    source_snapshot: {
      id: 9,
      snapshot_id: "capture-9",
      scanner_id: "windows-scanner-a",
      scanner_version: "0.4.0",
      schema_version: 1,
      observed_at: "2026-09-16T12:00:00Z",
      received_at: "2026-09-16T12:00:01Z",
      cycle_ref: "cycle-example",
    },
    buildings_present: true,
    posts_present: true,
    buildings: [],
    posts: [],
    ...overrides,
  };
}

function renderPanel() {
  return renderWithProviders(
    <>
      <div>Planned board remains available</div>
      <ScannerEvidencePanel siegeId={42} />
    </>
  );
}

describe("ScannerEvidencePanel", () => {
  it("shows an independent loading state", () => {
    server.use(
      http.get("/api/sieges/42/scanner-evidence", async () => {
        await new Promise(() => {});
      })
    );

    renderPanel();

    expect(
      screen.getByText("Planned board remains available")
    ).toBeInTheDocument();
    expect(screen.getByText("Loading scanner evidence...")).toBeInTheDocument();
  });

  it("renders no evidence as a normal explicit state with UNKNOWN presence omitted", async () => {
    server.use(
      http.get("/api/sieges/42/scanner-evidence", () =>
        HttpResponse.json(
          evidenceResponse({
            has_evidence: false,
            source_snapshot: null,
            buildings_present: null,
            posts_present: null,
          })
        )
      )
    );

    renderPanel();

    expect(
      await screen.findByText("No scanner evidence available for this Siege.")
    ).toBeInTheDocument();
    expect(screen.queryByText("Observed Buildings")).not.toBeInTheDocument();
    expect(screen.queryByText("Observed Posts")).not.toBeInTheDocument();
  });

  it("shows source metadata without trust semantics and preserves true/false presence", async () => {
    server.use(
      http.get("/api/sieges/42/scanner-evidence", () =>
        HttpResponse.json(
          evidenceResponse({
            buildings_present: true,
            posts_present: false,
          })
        )
      )
    );

    renderPanel();

    expect(await screen.findByText("windows-scanner-a")).toBeInTheDocument();
    expect(screen.getByText("capture-9")).toBeInTheDocument();
    expect(screen.getByText("0.4.0")).toBeInTheDocument();
    expect(screen.getByText("Observed")).toBeInTheDocument();
    expect(screen.getByText("Not observed")).toBeInTheDocument();
    expect(
      screen.queryByText(/trusted|leader|authoritative|primary scanner/i)
    ).not.toBeInTheDocument();
  });

  it("renders UNKNOWN separately and keeps modifier IDs in backend order", async () => {
    server.use(
      http.get("/api/sieges/42/scanner-evidence", () =>
        HttpResponse.json(
          evidenceResponse({
            buildings: [
              {
                external_building_id: "building-unknown",
                level: null,
                is_broken: null,
              },
              {
                external_building_id: "building-known-false",
                level: 2,
                is_broken: false,
              },
            ],
            posts: [
              {
                external_post_id: "post-ordered",
                modifier_ids: ["710012", "710007", "710010"],
              },
              {
                external_post_id: "post-unknown",
                modifier_ids: null,
              },
              {
                external_post_id: "post-empty",
                modifier_ids: [],
              },
            ],
          })
        )
      )
    );

    renderPanel();

    expect(await screen.findByText("building-unknown")).toBeInTheDocument();
    expect(screen.getByText("Level: Unknown")).toBeInTheDocument();
    expect(screen.getByText("Broken: Unknown")).toBeInTheDocument();
    expect(screen.getByText("Broken: No")).toBeInTheDocument();
    expect(screen.getByText("Modifiers: Unknown")).toBeInTheDocument();
    expect(screen.getByText("No modifiers observed")).toBeInTheDocument();

    const modifiers = within(
      screen.getAllByLabelText("Observed modifiers")[0]
    ).getAllByText(/7100/);
    expect(modifiers.map((element) => element.textContent)).toEqual([
      "710012",
      "710007",
      "710010",
    ]);
  });

  it("does not retain evidence from the previous Siege while a new key loads", async () => {
    let releaseSecondRequest!: () => void;
    const secondRequest = new Promise<void>((resolve) => {
      releaseSecondRequest = resolve;
    });
    server.use(
      http.get("/api/sieges/42/scanner-evidence", () =>
        HttpResponse.json(evidenceResponse())
      ),
      http.get("/api/sieges/43/scanner-evidence", async () => {
        await secondRequest;
        return HttpResponse.json({
          siege_id: 43,
          has_evidence: false,
          source_snapshot: null,
          buildings_present: null,
          posts_present: null,
          buildings: [],
          posts: [],
        });
      })
    );

    const view = renderWithProviders(<ScannerEvidencePanel siegeId={42} />);
    expect(await screen.findByText("windows-scanner-a")).toBeInTheDocument();

    view.rerender(<ScannerEvidencePanel siegeId={43} />);

    expect(screen.queryByText("windows-scanner-a")).not.toBeInTheDocument();
    expect(screen.getByText("Loading scanner evidence...")).toBeInTheDocument();

    releaseSecondRequest();
    expect(
      await screen.findByText("No scanner evidence available for this Siege.")
    ).toBeInTheDocument();
  });

  it("keeps the surrounding Siege UI available when evidence loading fails", async () => {
    server.use(
      http.get("/api/sieges/42/scanner-evidence", () =>
        HttpResponse.json({ detail: "failure" }, { status: 500 })
      )
    );

    renderPanel();

    expect(
      await screen.findByText("Unable to load scanner evidence.")
    ).toBeInTheDocument();
    expect(
      screen.getByText("Planned board remains available")
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Scanner Evidence" })
    ).toBeInTheDocument();
  });
});
