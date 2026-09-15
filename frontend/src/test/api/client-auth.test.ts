import { http, HttpResponse } from "msw";
import {
  afterAll,
  afterEach,
  beforeAll,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import apiClient from "../../api/client";
import { server } from "../server";

beforeAll(() => server.listen({ onUnhandledRequest: "warn" }));
afterEach(() => {
  server.resetHandlers();
  vi.restoreAllMocks();
});
afterAll(() => server.close());

describe("API permission errors", () => {
  it("announces 403 without redirecting to login", async () => {
    server.use(
      http.get("/api/forbidden", () => new HttpResponse(null, { status: 403 }))
    );
    const spy = vi.spyOn(window, "dispatchEvent");
    await expect(apiClient.get("/api/forbidden")).rejects.toBeTruthy();
    expect(spy).toHaveBeenCalledWith(
      expect.objectContaining({ type: "manager:permission-denied" })
    );
  });
});
