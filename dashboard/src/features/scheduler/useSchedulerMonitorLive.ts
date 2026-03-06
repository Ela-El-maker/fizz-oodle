"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { fetchSchedulerMonitorSnapshot } from "@/entities/scheduler/monitor.api";
import {
  SchedulerMonitorSnapshotSchema,
  SchedulerMonitorWsMessageSchema,
  type SchedulerMonitorSnapshot,
} from "@/entities/scheduler/monitor.schema";

type TransportMode = "connecting" | "ws" | "polling";

function toWsUrl(path: string): string {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  return `${protocol}://${window.location.host}${path}`;
}

export function useSchedulerMonitorLive() {
  const [snapshot, setSnapshot] = useState<SchedulerMonitorSnapshot | null>(null);
  const [transport, setTransport] = useState<TransportMode>("connecting");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const pollTimerRef = useRef<number | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let mounted = true;

    const clearPolling = () => {
      if (pollTimerRef.current) {
        window.clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };

    const clearReconnect = () => {
      if (reconnectTimerRef.current) {
        window.clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
    };

    const loadSnapshot = async () => {
      try {
        const data = await fetchSchedulerMonitorSnapshot();
        if (!mounted) return;
        setSnapshot(data);
        setError(null);
        setIsLoading(false);
      } catch (err) {
        if (!mounted) return;
        setError(err instanceof Error ? err.message : "Failed to fetch scheduler monitor snapshot");
        setIsLoading(false);
      }
    };

    const startPolling = () => {
      setTransport("polling");
      void loadSnapshot();
      clearPolling();
      pollTimerRef.current = window.setInterval(() => {
        void loadSnapshot();
      }, 5000);
    };

    const connectWs = () => {
      clearReconnect();
      try {
        const ws = new WebSocket(toWsUrl("/api/scheduler/monitor/ws"));
        wsRef.current = ws;

        ws.onopen = () => {
          if (!mounted) return;
          setTransport("ws");
          setError(null);
          setIsLoading(false);
          clearPolling();
        };

        ws.onmessage = (event) => {
          if (!mounted) return;
          let raw: unknown;
          try {
            raw = JSON.parse(event.data);
          } catch {
            return;
          }
          const parsed = SchedulerMonitorWsMessageSchema.safeParse(raw);
          if (!parsed.success) {
            setError("Live scheduler frame parse failed; falling back to polling");
            startPolling();
            return;
          }

          if (parsed.data.type === "snapshot" && parsed.data.data) {
            const snap = SchedulerMonitorSnapshotSchema.safeParse(parsed.data.data);
            if (snap.success) {
              setSnapshot(snap.data);
              setError(null);
              setIsLoading(false);
            } else {
              setError("Live scheduler snapshot parse failed; using polling fallback");
              startPolling();
            }
          } else if (parsed.data.type === "degraded") {
            setError(parsed.data.reason || "WS degraded");
          }
        };

        ws.onerror = () => {
          if (!mounted) return;
          setError("WebSocket transport error");
        };

        ws.onclose = () => {
          if (!mounted) return;
          setTransport("polling");
          startPolling();
          clearReconnect();
          reconnectTimerRef.current = window.setTimeout(() => {
            connectWs();
          }, 3000);
        };
      } catch (err) {
        if (!mounted) return;
        setError(err instanceof Error ? err.message : "Failed to connect WebSocket");
        startPolling();
      }
    };

    void loadSnapshot();
    connectWs();

    return () => {
      mounted = false;
      clearPolling();
      clearReconnect();
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.close();
      }
      wsRef.current = null;
    };
  }, []);

  return useMemo(
    () => ({
      snapshot,
      transport,
      isLoading,
      error,
    }),
    [snapshot, transport, isLoading, error],
  );
}
