"use client";

import { useState } from "react";

export function useFilterState<T extends object>(initial: T) {
  const [filters, setFilters] = useState<T>(initial);
  return { filters, setFilters };
}
