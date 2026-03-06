"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchRuns } from "@/entities/run/api";

export function useRunsPolling(limit = 25) {
  return useQuery({
    queryKey: ["runs", limit],
    queryFn: () => fetchRuns({ limit }),
    refetchInterval: 5000,
  });
}
