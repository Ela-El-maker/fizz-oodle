"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchHealth } from "@/entities/system/api";

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: fetchHealth,
    refetchInterval: 15000,
  });
}
