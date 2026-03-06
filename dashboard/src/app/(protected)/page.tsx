"use client";

import { useState } from "react";

import { OpsMonitorDashboard } from "@/widgets/ops-console/OpsMonitorDashboard";
import { OpsConsole } from "@/widgets/ops-console/OpsConsole";
import { Panel } from "@/shared/ui/Panel";
import { Tabs } from "@/shared/ui/Tabs";

export default function OverviewPage() {
  const [tab, setTab] = useState("mission");
  return (
    <div className="space-y-4">
      <Panel>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold text-ink">Overview</h1>
            <p className="text-sm text-muted">Primary live operations overview plus legacy console access.</p>
          </div>
          <Tabs
            items={[
              { key: "mission", label: "Mission Overview" },
              { key: "legacy", label: "Legacy Ops Console" },
            ]}
            activeKey={tab}
            onChange={setTab}
          />
        </div>
      </Panel>
      {tab === "mission" ? <OpsMonitorDashboard /> : <OpsConsole initialTab="logs" />}
    </div>
  );
}
