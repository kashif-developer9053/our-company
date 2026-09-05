"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { OUTREACH_TREND } from "@/data/outreachReport.mock";

// 7-day outreach volume chart (placeholder data) for the Reports dashboard.
export default function OutreachChart() {
  return (
    <div className="chart-wrap">
      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={OUTREACH_TREND} margin={{ top: 8, right: 12, left: -12, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#232b3a" vertical={false} />
          <XAxis dataKey="day" stroke="#6b7383" fontSize={12} tickLine={false} />
          <YAxis stroke="#6b7383" fontSize={12} tickLine={false} axisLine={false} />
          <Tooltip
            cursor={{ fill: "rgba(255,255,255,0.04)" }}
            contentStyle={{
              background: "#141926",
              border: "1px solid #2a3040",
              borderRadius: 8,
              color: "#e6e6e6",
              fontSize: 12,
            }}
          />
          <Legend wrapperStyle={{ fontSize: 12, color: "#8a93a6" }} />
          <Bar dataKey="emailsSent" name="Emails Sent" fill="#4aa3ff" radius={[3, 3, 0, 0]} />
          <Bar dataKey="replies" name="Replies" fill="#59c48a" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
