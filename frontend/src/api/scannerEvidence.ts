import apiClient from "./client";
import type { SiegeScannerEvidenceResponse } from "./types";

export async function getSiegeScannerEvidence(
  siegeId: number
): Promise<SiegeScannerEvidenceResponse> {
  const response = await apiClient.get<SiegeScannerEvidenceResponse>(
    `/api/sieges/${siegeId}/scanner-evidence`
  );
  return response.data;
}
