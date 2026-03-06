"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { triggerAgent } from "@/entities/run/api";

export function useTriggerAgent() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ agent, params }: { agent: string; params?: Record<string, string | boolean | undefined> }) =>
      triggerAgent(agent, params),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["runs"] });
      void queryClient.invalidateQueries({ queryKey: ["health"] });
    },
  });
}
