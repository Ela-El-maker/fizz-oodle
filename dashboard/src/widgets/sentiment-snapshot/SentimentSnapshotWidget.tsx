"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchSentimentDigestLatest } from "@/entities/sentiment/api";
import { Panel } from "@/shared/ui/Panel";
import { Badge } from "@/shared/ui/Badge";
import { fmtDateTime } from "@/shared/lib/format";
import { normalizeStatus } from "@/shared/lib/status";

export function SentimentSnapshotWidget() {
  const digest = useQuery({ queryKey: ["sentiment-digest-latest"], queryFn: fetchSentimentDigestLatest, refetchInterval: 60000 });

  if (digest.isLoading) return <Panel title="Sentiment Snapshot">Loading...</Panel>;
  if (digest.isError) return <Panel title="Sentiment Snapshot">Failed to load digest.</Panel>;

  return (
    <Panel title="Sentiment Snapshot">
      <div className="space-y-2 text-sm">
        <div className="flex items-center gap-2">
          <Badge value={normalizeStatus(digest.data?.item?.status)} />
          <span className="text-muted">Week: {digest.data?.item?.week_start || "-"}</span>
        </div>
        <div className="text-xs text-ink-faint">Sent at: {fmtDateTime(digest.data?.item?.sent_at)}</div>
      </div>
    </Panel>
  );
}
