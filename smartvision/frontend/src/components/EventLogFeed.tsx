"use client";

import React, { useMemo, useState } from "react";
import {
  AlertCircle,
  AlertTriangle,
  Clock,
  Filter,
  Info,
  RotateCcw,
  Search,
  ShieldAlert,
  Trash2,
} from "lucide-react";
import { AlertEventPayload, AlertSeverity } from "../types/protocol";

interface EventLogFeedProps {
  alerts: AlertEventPayload[];
  onClearLogs: () => void;
}

export function EventLogFeed({ alerts, onClearLogs }: EventLogFeedProps) {
  const [selectedSeverity, setSelectedSeverity] = useState<AlertSeverity | "all">("all");
  const [searchQuery, setSearchQuery] = useState("");

  const filteredAlerts = useMemo(() => {
    return alerts.filter((alert) => {
      if (selectedSeverity !== "all" && alert.severity !== selectedSeverity) {
        return false;
      }
      if (searchQuery.trim() !== "") {
        const query = searchQuery.toLowerCase();
        const text = `${alert.event_type} ${alert.message} ${alert.source}`.toLowerCase();
        if (!text.includes(query)) return false;
      }
      return true;
    });
  }, [alerts, selectedSeverity, searchQuery]);

  const formatTimestamp = (ts?: number) => {
    if (!ts) return "--:--:--";
    const date = new Date(ts);
    return date.toLocaleTimeString([], { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
  };

  const getSeverityBadge = (severity: AlertSeverity) => {
    switch (severity) {
      case "critical":
        return (
          <span className="flex items-center space-x-1 px-1.5 py-0.5 rounded bg-rose-950 text-rose-400 border border-rose-500/40 text-[10px] font-bold uppercase">
            <AlertCircle className="w-3 h-3 text-rose-500" />
            <span>CRIT</span>
          </span>
        );
      case "warning":
        return (
          <span className="flex items-center space-x-1 px-1.5 py-0.5 rounded bg-amber-950 text-amber-400 border border-amber-500/40 text-[10px] font-bold uppercase">
            <AlertTriangle className="w-3 h-3 text-amber-500" />
            <span>WARN</span>
          </span>
        );
      case "info":
      default:
        return (
          <span className="flex items-center space-x-1 px-1.5 py-0.5 rounded bg-cyan-950 text-cyan-400 border border-cyan-500/40 text-[10px] font-bold uppercase">
            <Info className="w-3 h-3 text-cyan-400" />
            <span>INFO</span>
          </span>
        );
    }
  };

  return (
    <div className="w-full rounded-xl bg-slate-900 border border-slate-800 p-4 shadow-xl flex flex-col space-y-3">
      {/* Header with Title and Clear Logs */}
      <div className="flex items-center justify-between border-b border-slate-800 pb-2.5">
        <div className="flex items-center space-x-2">
          <ShieldAlert className="w-4 h-4 text-amber-400" />
          <h3 className="font-mono text-sm font-bold uppercase tracking-wider text-slate-100">
            System Event & Alert Feed
          </h3>
        </div>
        <div className="flex items-center space-x-2">
          <span className="text-xs font-mono text-slate-400">
            {filteredAlerts.length} Events
          </span>
          {alerts.length > 0 && (
            <button
              onClick={onClearLogs}
              title="Clear event logs"
              className="p-1 rounded hover:bg-slate-800 text-slate-400 hover:text-rose-400 transition-colors"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs font-mono">
        {/* Severity Filter Tabs */}
        <div className="flex items-center space-x-1 bg-slate-950 p-1 rounded-lg border border-slate-800">
          {(["all", "info", "warning", "critical"] as const).map((sev) => {
            const isActive = selectedSeverity === sev;
            return (
              <button
                key={sev}
                onClick={() => setSelectedSeverity(sev)}
                className={`px-2 py-0.5 rounded uppercase transition-colors ${
                  isActive
                    ? "bg-slate-800 text-slate-100 font-semibold shadow"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                {sev}
              </button>
            );
          })}
        </div>

        {/* Text Filter Input */}
        <div className="relative flex-1 min-w-[160px]">
          <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            type="text"
            placeholder="Search events..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full bg-slate-950 border border-slate-800 rounded-lg pl-8 pr-2 py-1 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-slate-700"
          />
        </div>
      </div>

      {/* Event Stream List */}
      <div className="max-h-64 overflow-y-auto space-y-1.5 pr-1 font-mono text-xs">
        {filteredAlerts.length > 0 ? (
          filteredAlerts.map((alert, idx) => (
            <div
              key={alert.event_id || `${alert.timestamp}-${idx}`}
              className="flex items-start space-x-2.5 p-2 rounded-lg bg-slate-950 border border-slate-800/80 hover:border-slate-700 transition-colors"
            >
              {/* Severity Pill */}
              <div className="flex-shrink-0 pt-0.5">
                {getSeverityBadge(alert.severity)}
              </div>

              {/* Event Content */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between space-x-2">
                  <span className="font-semibold text-slate-200 truncate">
                    {alert.event_type.replace(/_/g, " ").toUpperCase()}
                  </span>
                  <div className="flex items-center space-x-1 text-[10px] text-slate-500 flex-shrink-0">
                    <Clock className="w-3 h-3" />
                    <span>{formatTimestamp(alert.timestamp)}</span>
                  </div>
                </div>

                <p className="text-slate-400 text-[11px] mt-0.5 break-words">
                  {alert.message}
                </p>

                {alert.action_taken && (
                  <div className="text-[10px] text-emerald-400/80 mt-1">
                    Action: {alert.action_taken}
                  </div>
                )}
              </div>
            </div>
          ))
        ) : (
          <div className="p-6 text-center rounded-lg bg-slate-950 border border-dashed border-slate-800 text-slate-500 font-mono text-xs">
            No events matching current filter criteria.
          </div>
        )}
      </div>
    </div>
  );
}
