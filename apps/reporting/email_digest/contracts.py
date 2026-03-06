from __future__ import annotations

from typing import TypedDict


class DigestLink(TypedDict, total=False):
    label: str
    url: str
    meta: str


class DigestExplainer(TypedDict):
    term: str
    meaning: str


class DigestStory(TypedDict, total=False):
    lane: str
    title: str
    theme: str | None
    impact_score: int | None
    confidence: str | None
    what_happened: str
    why_matters: str
    who_affected: str
    watch_next: str
    sources: list[DigestLink]


class DigestOneMinute(TypedDict):
    headline: str
    summary: str
    confidence: str
    sources: list[DigestLink]


class DigestKpi(TypedDict):
    label: str
    value: str


class ExecutiveDigestPayload(TypedDict):
    date_label: str
    kpis: list[DigestKpi]
    one_minute: DigestOneMinute
    inside_kenya: list[DigestStory]
    outside_kenya: list[DigestStory]
    global_to_kenya: list[str]
    global_driver_links: list[DigestLink]
    watchlist: list[str]
    read_more: list[DigestLink]
    explainers: list[DigestExplainer]
    data_quality: list[str]
