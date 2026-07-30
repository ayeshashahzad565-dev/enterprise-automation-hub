"use client";

import {
  Bar,
  CartesianGrid,
  Cell,
  BarChart as RechartsBarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export interface BarChartDatum {
  key: string;
  label: string;
  value: number;
  color?: string;
}

/** Horizontal bar chart — for distribution/comparison questions (status breakdown, department comparison, workload). */
export function BarChart({
  data,
  onBarClick,
  height = 260,
}: {
  data: BarChartDatum[];
  onBarClick?: (datum: BarChartDatum) => void;
  height?: number | `${number}%`;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <RechartsBarChart data={data} layout="vertical" margin={{ left: 8, right: 16, top: 8, bottom: 8 }}>
        <CartesianGrid strokeDasharray="3 3" horizontal={false} className="stroke-border" />
        <XAxis type="number" allowDecimals={false} tick={{ fontSize: 12 }} />
        <YAxis type="category" dataKey="label" width={110} tick={{ fontSize: 12 }} />
        <Tooltip
          cursor={{ fill: "var(--muted)" }}
          contentStyle={{
            background: "var(--popover)",
            border: "1px solid var(--border)",
            borderRadius: 8,
            fontSize: 12,
          }}
        />
        <Bar
          dataKey="value"
          radius={[0, 4, 4, 0]}
          onClick={onBarClick ? (datum: unknown) => onBarClick(datum as BarChartDatum) : undefined}
          cursor={onBarClick ? "pointer" : undefined}
        >
          {data.map((entry) => (
            <Cell key={entry.key} fill={entry.color ?? "var(--primary)"} />
          ))}
        </Bar>
      </RechartsBarChart>
    </ResponsiveContainer>
  );
}
