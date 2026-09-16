import { http, HttpResponse } from "msw";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { getSiegeScannerEvidence } from "../../api/scannerEvidence";
import type { SiegeScannerEvidenceResponse } from "../../api/types";
import { server } from "../server";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("getSiegeScannerEvidence", () => {
  it("uses the Task #9 endpoint and preserves the no-evidence null state", async () => {
    let requestedPath = "";
    const responseBody: SiegeScannerEvidenceResponse = {
      siege_id: 73,
      has_evidence: false,
      source_snapshot: null,
      buildings_present: null,
      posts_present: null,
      buildings: [],
      posts: [],
    };
    server.use(
      http.get("/api/sieges/73/scanner-evidence", ({ request }) => {
        requestedPath = new URL(request.url).pathname;
        return HttpResponse.json(responseBody);
      })
    );

    const response = await getSiegeScannerEvidence(73);

    expect(requestedPath).toBe("/api/sieges/73/scanner-evidence");
    expect(response).toEqual(responseBody);
    expect(response.buildings_present).toBeNull();
    expect(response.posts_present).toBeNull();
  });

  it("preserves observed values, UNKNOWN nulls, presence and modifier order", async () => {
    const responseBody: SiegeScannerEvidenceResponse = {
      siege_id: 73,
      has_evidence: true,
      source_snapshot: {
        id: 14,
        snapshot_id: "capture-14",
        scanner_id: "scanner-windows",
        scanner_version: "0.4.0",
        schema_version: 1,
        observed_at: "2026-09-16T12:00:00Z",
        received_at: "2026-09-16T12:00:01Z",
        cycle_ref: null,
      },
      buildings_present: true,
      posts_present: false,
      buildings: [
        {
          external_building_id: "building-raw",
          level: null,
          is_broken: false,
        },
      ],
      posts: [
        {
          external_post_id: "post-raw",
          modifier_ids: ["modifier-z", "modifier-a"],
        },
      ],
    };
    server.use(
      http.get("/api/sieges/73/scanner-evidence", () =>
        HttpResponse.json(responseBody)
      )
    );

    const response = await getSiegeScannerEvidence(73);

    expect(response).toEqual(responseBody);
    expect(response.buildings[0].level).toBeNull();
    expect(response.buildings[0].is_broken).toBe(false);
    expect(response.buildings_present).toBe(true);
    expect(response.posts_present).toBe(false);
    expect(response.posts[0].modifier_ids).toEqual([
      "modifier-z",
      "modifier-a",
    ]);
  });
});
