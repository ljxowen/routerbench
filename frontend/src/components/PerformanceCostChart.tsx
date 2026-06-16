import { useEffect, useState } from "react"
import {
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { ChartData, fetchChartData } from "../api/client"

type Props = { evalNames: string[] }

// A plotted coordinate. `label` is what the tooltip shows for this marker.
type Point = { x: number; y: number; label: string }

// Distinct colors for the router curves; LLMs / oracle / zero-router use fixed
// colors below so they read the same across benchmarks.
const ROUTER_COLORS = ["#2563eb", "#16a34a", "#9333ea", "#0891b2", "#db2777"]
const LLM_COLOR = "#9ca3af"
const ORACLE_COLOR = "#f59e0b"
const ZERO_COLOR = "#6b7280"

// Line-only series (NDCH / zero-router) render no markers; the connecting line
// is drawn from the `line` prop independently of the point shape.
const NoMarker = (_props: unknown): null => null

function toPoints(
  arr: { total_cost: number; performance: number }[],
  label: string
): Point[] {
  return arr.map((p) => ({ x: p.total_cost, y: p.performance, label }))
}

// Clip the performance axis to the data's actual range (plus a small margin)
// instead of a fixed [0, 1], so the curves fill the vertical space.
function performanceDomain(data: ChartData): [number, number] {
  const ys: number[] = []
  for (const r of data.routers) {
    for (const p of r.points) ys.push(p.performance)
    for (const p of r.ndch) ys.push(p.performance)
  }
  for (const m of data.llms) ys.push(m.performance)
  if (data.oracle) ys.push(data.oracle.performance)
  for (const p of data.zero_router_ndch) ys.push(p.performance)
  if (ys.length === 0) return [0, 1]
  const min = Math.min(...ys)
  const max = Math.max(...ys)
  const pad = Math.max((max - min) * 0.08, 0.01)
  return [Math.max(0, min - pad), Math.min(1, max + pad)]
}

export default function PerformanceCostChart({ evalNames }: Props) {
  const [evalName, setEvalName] = useState(evalNames[0] ?? "")
  const [data, setData] = useState<ChartData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!evalName) return
    setLoading(true)
    setError(null)
    fetchChartData(evalName)
      .then(setData)
      .catch(() => setError("Failed to load chart data"))
      .finally(() => setLoading(false))
  }, [evalName])

  const llmPoints = data
    ? data.llms.map((m) => ({ x: m.total_cost, y: m.performance, label: m.display }))
    : []
  const oraclePoints = data?.oracle
    ? [{ x: data.oracle.total_cost, y: data.oracle.performance, label: "Oracle" }]
    : []
  const zeroPoints = data ? toPoints(data.zero_router_ndch, "Zero router") : []

  return (
    <div>
      <div style={{ display: "flex", gap: 12, marginBottom: 16, flexWrap: "wrap" }}>
        <select value={evalName} onChange={(e) => setEvalName(e.target.value)} style={sel}>
          {evalNames.map((n) => (
            <option key={n} value={n}>{n}</option>
          ))}
        </select>
        <span style={{ color: "#6b7280", fontSize: 13, alignSelf: "center" }}>
          Performance vs. cost — matches the offline visualizer (NDCH frontier per router)
        </span>
      </div>

      {loading && <p style={{ color: "#6b7280" }}>Loading...</p>}
      {error && <p style={{ color: "red" }}>{error}</p>}

      {!loading && !error && data && (
        <ResponsiveContainer width="100%" height={520}>
          <ScatterChart margin={{ top: 16, right: 24, bottom: 48, left: 16 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
            <XAxis
              type="number"
              dataKey="x"
              name="Cost"
              tickFormatter={(v) => `$${Number(v).toFixed(2)}`}
              label={{ value: "Total cost ($)", position: "insideBottom", offset: -12 }}
            />
            <YAxis
              type="number"
              dataKey="y"
              name="Performance"
              domain={performanceDomain(data)}
              tickFormatter={(v) => `${(Number(v) * 100).toFixed(0)}%`}
              label={{ value: "Performance", angle: -90, position: "insideLeft" }}
            />
            <Tooltip cursor={{ strokeDasharray: "3 3" }} content={<ChartTooltip />} />
            <Legend wrapperStyle={{ paddingTop: 16 }} />

            {data.routers.map((r, i) => {
              const color = ROUTER_COLORS[i % ROUTER_COLORS.length]
              return [
                // NDCH frontier: solid line, no markers, shown in the legend.
                <Scatter
                  key={`${r.display}-ndch`}
                  name={r.display}
                  data={toPoints(r.ndch, `${r.display} NDCH`)}
                  fill={color}
                  line={{ stroke: color, strokeWidth: 2 }}
                  lineType="joint"
                  shape={NoMarker}
                  isAnimationActive={false}
                />,
                // Operating points: dotted line with × markers, hidden from legend
                // to avoid doubling each router entry.
                <Scatter
                  key={`${r.name}-points`}
                  name={r.name}
                  legendType="none"
                  data={toPoints(r.points, r.name)}
                  fill={color}
                  line={{ stroke: color, strokeWidth: 1, strokeDasharray: "4 4" }}
                  lineType="joint"
                  shape="cross"
                  isAnimationActive={false}
                />,
              ]
            })}

            {llmPoints.length > 0 && (
              <Scatter
                name="LLMs"
                data={llmPoints}
                fill={LLM_COLOR}
                shape="circle"
                isAnimationActive={false}
              />
            )}
            {zeroPoints.length > 0 && (
              <Scatter
                name="Zero router"
                data={zeroPoints}
                fill={ZERO_COLOR}
                line={{ stroke: ZERO_COLOR, strokeWidth: 2 }}
                lineType="joint"
                shape={NoMarker}
                isAnimationActive={false}
              />
            )}
            {oraclePoints.length > 0 && (
              <Scatter
                name="Oracle"
                data={oraclePoints}
                fill={ORACLE_COLOR}
                shape="star"
                isAnimationActive={false}
              />
            )}
          </ScatterChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}

type TooltipProps = { active?: boolean; payload?: Array<{ payload: Point }> }

function ChartTooltip({ active, payload }: TooltipProps) {
  if (!active || !payload?.length) return null
  const p = payload[0].payload
  return (
    <div style={{
      background: "#fff", border: "1px solid #d1d5db", borderRadius: 6,
      padding: "8px 12px", fontSize: 13, boxShadow: "0 1px 4px rgba(0,0,0,0.1)",
    }}>
      <div style={{ fontWeight: 600, marginBottom: 4 }}>{p.label}</div>
      <div style={{ color: "#374151" }}>Performance: {(p.y * 100).toFixed(1)}%</div>
      <div style={{ color: "#374151" }}>Cost: ${p.x.toFixed(4)}</div>
    </div>
  )
}

const sel = { padding: "6px 10px", borderRadius: 4, border: "1px solid #d1d5db", fontSize: 13 }
