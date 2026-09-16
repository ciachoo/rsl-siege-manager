import { useQuery } from "@tanstack/react-query";
import { getSiegeScannerEvidence } from "../api/scannerEvidence";
import type { ObservedBuilding, ObservedPost } from "../api/types";
import { Badge } from "./ui/badge";

function presenceLabel(value: boolean | null): string {
  if (value === null) return "Unknown";
  return value ? "Observed" : "Not observed";
}

function unknownValue(value: number | null): string {
  return value === null ? "Unknown" : String(value);
}

function brokenValue(value: boolean | null): string {
  if (value === null) return "Unknown";
  return value ? "Yes" : "No";
}

function ObservedBuildingRow({ building }: { building: ObservedBuilding }) {
  return (
    <li className="rounded-md border border-slate-200 bg-white px-3 py-2">
      <div className="font-mono text-xs font-semibold text-slate-800">
        {building.external_building_id}
      </div>
      <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600">
        <span>Level: {unknownValue(building.level)}</span>
        <span>Broken: {brokenValue(building.is_broken)}</span>
      </div>
    </li>
  );
}

function ObservedPostRow({ post }: { post: ObservedPost }) {
  return (
    <li className="rounded-md border border-slate-200 bg-white px-3 py-2">
      <div className="font-mono text-xs font-semibold text-slate-800">
        {post.external_post_id}
      </div>
      <div
        className="mt-2 flex flex-wrap gap-1"
        aria-label="Observed modifiers"
      >
        {post.modifier_ids === null ? (
          <span className="text-xs text-slate-500">Modifiers: Unknown</span>
        ) : post.modifier_ids.length === 0 ? (
          <span className="text-xs text-slate-500">No modifiers observed</span>
        ) : (
          post.modifier_ids.map((modifierId, index) => (
            <Badge
              key={`${modifierId}-${index}`}
              variant="secondary"
              className="font-mono text-xs"
            >
              {modifierId}
            </Badge>
          ))
        )}
      </div>
    </li>
  );
}

export function ScannerEvidencePanel({ siegeId }: { siegeId: number }) {
  const evidenceQuery = useQuery({
    queryKey: ["siegeScannerEvidence", siegeId],
    queryFn: () => getSiegeScannerEvidence(siegeId),
    enabled: Number.isInteger(siegeId) && siegeId > 0,
  });

  return (
    <section
      aria-labelledby="scanner-evidence-heading"
      className="mb-4 rounded-lg border border-slate-200 bg-slate-50 p-4"
    >
      <div>
        <h2
          id="scanner-evidence-heading"
          className="text-base font-semibold text-slate-900"
        >
          Scanner Evidence
        </h2>
        <p className="text-xs text-slate-500">
          Observed by Scanner · read-only evidence, separate from the planned
          board.
        </p>
      </div>

      {evidenceQuery.isPending && (
        <p className="mt-3 text-sm text-slate-500">
          Loading scanner evidence...
        </p>
      )}

      {evidenceQuery.isError && (
        <p role="alert" className="mt-3 text-sm text-amber-700">
          Unable to load scanner evidence.
        </p>
      )}

      {evidenceQuery.data && !evidenceQuery.data.has_evidence && (
        <p className="mt-3 text-sm text-slate-600">
          No scanner evidence available for this Siege.
        </p>
      )}

      {evidenceQuery.data?.has_evidence &&
        evidenceQuery.data.source_snapshot && (
          <div className="mt-3 space-y-4">
            <div className="rounded-md border border-slate-200 bg-white p-3">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Source / Observation
              </h3>
              <dl className="mt-2 grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2 lg:grid-cols-4">
                <div>
                  <dt className="text-xs text-slate-500">Scanner</dt>
                  <dd className="break-all font-mono text-xs text-slate-800">
                    {evidenceQuery.data.source_snapshot.scanner_id}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-slate-500">Observed at</dt>
                  <dd className="text-xs text-slate-800">
                    <time
                      dateTime={evidenceQuery.data.source_snapshot.observed_at}
                    >
                      {new Date(
                        evidenceQuery.data.source_snapshot.observed_at
                      ).toLocaleString()}
                    </time>
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-slate-500">Scanner version</dt>
                  <dd className="break-all font-mono text-xs text-slate-800">
                    {evidenceQuery.data.source_snapshot.scanner_version}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-slate-500">Snapshot</dt>
                  <dd className="break-all font-mono text-xs text-slate-800">
                    {evidenceQuery.data.source_snapshot.snapshot_id}
                  </dd>
                </div>
              </dl>
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
              <div>
                <div className="mb-2 flex items-center justify-between gap-2">
                  <h3 className="text-sm font-semibold text-slate-800">
                    Observed Buildings
                  </h3>
                  <Badge variant="outline">
                    {presenceLabel(evidenceQuery.data.buildings_present)}
                  </Badge>
                </div>
                {evidenceQuery.data.buildings.length === 0 ? (
                  <p className="text-sm text-slate-500">
                    No observed building records.
                  </p>
                ) : (
                  <ul className="space-y-2">
                    {evidenceQuery.data.buildings.map((building) => (
                      <ObservedBuildingRow
                        key={building.external_building_id}
                        building={building}
                      />
                    ))}
                  </ul>
                )}
              </div>

              <div>
                <div className="mb-2 flex items-center justify-between gap-2">
                  <h3 className="text-sm font-semibold text-slate-800">
                    Observed Posts
                  </h3>
                  <Badge variant="outline">
                    {presenceLabel(evidenceQuery.data.posts_present)}
                  </Badge>
                </div>
                {evidenceQuery.data.posts.length === 0 ? (
                  <p className="text-sm text-slate-500">
                    No observed post records.
                  </p>
                ) : (
                  <ul className="space-y-2">
                    {evidenceQuery.data.posts.map((post) => (
                      <ObservedPostRow
                        key={post.external_post_id}
                        post={post}
                      />
                    ))}
                  </ul>
                )}
              </div>
            </div>
          </div>
        )}
    </section>
  );
}
