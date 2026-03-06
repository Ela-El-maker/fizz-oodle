type PriceRow = {
  ticker: string;
  open?: number | null;
  close?: number | null;
  volume?: number | null;
};

type SentimentRow = {
  ticker?: string | null;
  mentions_count?: number | null;
  mentions?: number | null;
  bullish_pct?: number | null;
  bearish_pct?: number | null;
  wow_delta?: number | null;
};

type PatternSummary = {
  active_count?: number;
  confirmed_count?: number;
};

type AnnouncementStats = {
  alerted?: number;
  total?: number;
};

type MarketStoryInput = {
  date: string;
  prices: PriceRow[];
  sentiment: SentimentRow[];
  patterns?: PatternSummary;
  announcements?: AnnouncementStats;
  analystContext?: string | null;
};

export type MarketStory = {
  headline: string;
  paragraphs: string[];
  evidence: string[];
};

const TICKER_SECTOR: Record<string, string> = {
  ABSA: "Banking",
  COOP: "Banking",
  KCB: "Banking",
  NCBA: "Banking",
  SBIC: "Banking",
  SCBK: "Banking",
  DTK: "Banking",
  EABL: "Consumer",
  BAT: "Consumer",
  NMG: "Media",
  SCOM: "Telecom",
  KQ: "Transport",
  JUB: "Insurance",
  BAMB: "Industrial",
};

function pct(open: number | null | undefined, close: number | null | undefined): number | null {
  if (open === null || open === undefined || open <= 0 || close === null || close === undefined) return null;
  return ((close - open) / open) * 100;
}

function fmtPct(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return `${value.toFixed(digits)}%`;
}

function median(values: number[]): number {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  if (sorted.length % 2 === 0) return (sorted[mid - 1] + sorted[mid]) / 2;
  return sorted[mid];
}

export function buildMarketStory(input: MarketStoryInput): MarketStory {
  const enriched = input.prices
    .map((row) => ({
      ...row,
      changePct: pct(row.open, row.close),
      volumeValue: row.volume ?? 0,
    }))
    .filter((row) => row.changePct !== null) as Array<PriceRow & { changePct: number; volumeValue: number }>;

  const advancers = enriched.filter((row) => row.changePct > 0).length;
  const decliners = enriched.filter((row) => row.changePct < 0).length;
  const unchanged = Math.max(0, enriched.length - advancers - decliners);
  const avgChange = enriched.length ? enriched.reduce((acc, row) => acc + row.changePct, 0) / enriched.length : 0;

  const topGainers = [...enriched].sort((a, b) => b.changePct - a.changePct).slice(0, 3);
  const topLosers = [...enriched].sort((a, b) => a.changePct - b.changePct).slice(0, 3);

  const volumes = enriched.map((row) => row.volumeValue).filter((v) => v > 0);
  const volMedian = median(volumes);
  const volumeSpikes = enriched
    .filter((row) => row.volumeValue > 0 && volMedian > 0 && row.volumeValue >= volMedian * 2)
    .sort((a, b) => b.volumeValue - a.volumeValue)
    .slice(0, 3);

  const sectorAgg = new Map<string, { sum: number; count: number }>();
  for (const row of enriched) {
    const sector = TICKER_SECTOR[row.ticker];
    if (!sector) continue;
    const prev = sectorAgg.get(sector) || { sum: 0, count: 0 };
    prev.sum += row.changePct;
    prev.count += 1;
    sectorAgg.set(sector, prev);
  }
  const sectorPerf = Array.from(sectorAgg.entries())
    .filter(([, v]) => v.count >= 2)
    .map(([sector, v]) => ({ sector, avg: v.sum / v.count }))
    .sort((a, b) => b.avg - a.avg);
  const strongestSector = sectorPerf[0];
  const weakestSector = sectorPerf[sectorPerf.length - 1];

  const sentimentRows = input.sentiment || [];
  const mentionsTotal = sentimentRows.reduce((acc, row) => acc + Number(row.mentions_count ?? row.mentions ?? 0), 0);
  const weightedBullish = mentionsTotal
    ? sentimentRows.reduce(
        (acc, row) => acc + Number(row.bullish_pct ?? 0) * Number(row.mentions_count ?? row.mentions ?? 0),
        0,
      ) / mentionsTotal
    : 0;
  const weightedBearish = mentionsTotal
    ? sentimentRows.reduce(
        (acc, row) => acc + Number(row.bearish_pct ?? 0) * Number(row.mentions_count ?? row.mentions ?? 0),
        0,
      ) / mentionsTotal
    : 0;
  const strongestSentiment = [...sentimentRows]
    .sort((a, b) => Number(b.bullish_pct ?? 0) - Number(a.bullish_pct ?? 0))
    .find((row) => (row.mentions_count ?? row.mentions ?? 0) > 0);

  const marketMood =
    decliners >= Math.max(1, advancers * 1.5)
      ? "bearish"
      : advancers >= Math.max(1, decliners * 1.5)
        ? "bullish"
        : "mixed";

  const p1 =
    marketMood === "bearish"
      ? `The market is leaning bearish on ${input.date}. Selling is broader than buying, and the average move across active tickers is ${fmtPct(avgChange)}.`
      : marketMood === "bullish"
        ? `The market is leaning bullish on ${input.date}. Buyers are carrying more names than sellers, with average intraday performance around ${fmtPct(avgChange)}.`
        : `The market is mixed on ${input.date}. Price action is balanced, and average movement is sitting around ${fmtPct(avgChange)}, which points to selective positioning rather than one-way risk appetite.`;

  const p2 = `Breadth shows ${advancers} advancers versus ${decliners} decliners, with ${unchanged} counters flat. This balance suggests ${
    decliners > advancers
      ? "risk is still tilted to the downside for most names"
      : advancers > decliners
        ? "buyers are still finding enough conviction to keep breadth constructive"
        : "the session is in a wait-and-see phase"
  }.`;

  const gainersText = topGainers
    .filter((row) => row.changePct > 0)
    .slice(0, 2)
    .map((row) => `${row.ticker} (${fmtPct(row.changePct)})`)
    .join(", ");
  const losersText = topLosers
    .filter((row) => row.changePct < 0)
    .slice(0, 2)
    .map((row) => `${row.ticker} (${fmtPct(row.changePct)})`)
    .join(", ");
  const p3 = `Leadership is split across a few names rather than broad participation. Bright spots include ${
    gainersText || "a limited set of gainers"
  }, while pressure is concentrated in ${losersText || "the weaker counters"}. ${
    strongestSector && weakestSector
      ? `${strongestSector.sector} is currently the strongest sectoral pocket, while ${weakestSector.sector} is dragging.`
      : "Sector leadership is still fragmented across the board."
  }`;

  const p4 =
    volumeSpikes.length > 0
      ? `Volume is not evenly distributed. Activity spikes are visible in ${volumeSpikes
          .map((row) => `${row.ticker} (${Math.round(row.volumeValue).toLocaleString()})`)
          .join(", ")}, which suggests institutions are concentrating risk in specific names instead of rotating across the whole board.`
      : "Volume flow is relatively even across names, which usually signals a calmer session with fewer conviction trades.";

  const p5 = `From the broader signal stack, conversation sentiment is ${
    weightedBullish - weightedBearish > 10
      ? "constructive"
      : weightedBearish - weightedBullish > 10
        ? "defensive"
        : "balanced"
  } (${fmtPct(weightedBullish)} bullish vs ${fmtPct(weightedBearish)} bearish across ${mentionsTotal.toLocaleString()} mentions). ${
    strongestSentiment?.ticker
      ? `${strongestSentiment.ticker} is currently one of the strongest sentiment leaders. `
      : ""
  }Pattern memory shows ${input.patterns?.active_count ?? 0} active setups (${input.patterns?.confirmed_count ?? 0} confirmed), while announcements monitor has flagged ${
    input.announcements?.alerted ?? 0
  } alerted events in its latest aggregate view.`;

  const paragraphs = [p1, p2, p3, p4, p5];
  if (input.analystContext && input.analystContext.trim().length > 0) {
    paragraphs.push(`Analyst engine context: ${input.analystContext.trim()}`);
  }

  return {
    headline:
      marketMood === "bearish"
        ? "MARKET STORY – TODAY'S SESSION: Broad selling pressure with selective resilience"
        : marketMood === "bullish"
          ? "MARKET STORY – TODAY'S SESSION: Buyers in control, but still selective"
          : "MARKET STORY – TODAY'S SESSION: Mixed tape with selective conviction",
    paragraphs,
    evidence: [
      `A: ${enriched.length} priced tickers`,
      `Breadth: ${advancers} up / ${decliners} down / ${unchanged} flat`,
      `C: ${mentionsTotal} sentiment mentions`,
      `E: ${input.patterns?.active_count ?? 0} active patterns`,
    ],
  };
}
