"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchLatestEmailValidation, runEmailValidation } from "@/entities/emailValidation/api";

export function useEmailValidation(window: "daily" | "weekly") {
  return useQuery({
    queryKey: ["email-validation", window],
    queryFn: () => fetchLatestEmailValidation(window),
    refetchInterval: 15000,
  });
}

export function useRunEmailValidation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (window: "daily" | "weekly") => runEmailValidation(window),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["email-validation"] });
      void queryClient.invalidateQueries({ queryKey: ["runs"] });
    },
  });
}
