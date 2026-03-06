export type AnnouncementFilters = {
  ticker?: string;
  type?: string;
  source_id?: string;
  scope?: "kenya_core" | "kenya_extended" | "global_outside" | "all";
  theme?: string;
  kenya_impact_min?: number;
  global_only?: boolean;
  limit?: number;
  offset?: number;
};
