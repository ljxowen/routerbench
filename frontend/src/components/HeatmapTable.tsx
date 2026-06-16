import { Row } from "../api/client"

type Props = { rows: Row[] }
type Cell = { performance: number; total_cost: number }

function perfToColor(value: number): string {
  const hue = Math.round(value * 120)
  return `hsl(${hue}, 60%, 88%)`
}

function buildGrid(rows: Row[]) {
  const evalSet = new Set<string>()
  const modelSet = new Set<string>()
  const grid: Record<string, Record<string, Cell>> = {}

  for (const row of rows) {
    evalSet.add(row.eval_name)
    const key = row.type === "llm" ? row.model_name : `${row.router_type} (router)`
    modelSet.add(key)
    if (!grid[row.eval_name]) grid[row.eval_name] = {}
    const cur = grid[row.eval_name][key]
    if (!cur || row.performance > cur.performance) {
      grid[row.eval_name][key] = { performance: row.performance, total_cost: row.total_cost }
    }
  }

  return {
    evalNames: Array.from(evalSet).sort(),
    modelNames: Array.from(modelSet).sort(),
    grid,
  }
}

export default function HeatmapTable({ rows }: Props) {
  const { evalNames, modelNames, grid } = buildGrid(rows)

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 16, fontSize: 12, color: "#6b7280" }}>
        <span>Low performance</span>
        {[0, 0.25, 0.5, 0.75, 1].map((v) => (
          <div key={v} style={{ width: 28, height: 18, borderRadius: 3, background: perfToColor(v) }} />
        ))}
        <span>High performance</span>
      </div>
      <div style={{ overflowX: "auto" }}>
        <table style={{ borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr style={{ background: "#f3f4f6" }}>
              <th style={th}>Benchmark</th>
              {modelNames.map((m) => (
                <th key={m} style={{ ...th, minWidth: 100, fontSize: 11 }}>{m}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {evalNames.map((evalName) => (
              <tr key={evalName}>
                <td style={{ ...td, fontWeight: 500, whiteSpace: "nowrap" as const }}>{evalName}</td>
                {modelNames.map((m) => {
                  const cell = grid[evalName]?.[m]
                  return (
                    <td key={m} style={{
                      ...td,
                      background: cell ? perfToColor(cell.performance) : "#f9fafb",
                      textAlign: "center" as const,
                      fontWeight: 500,
                    }}>
                      {cell ? `${(cell.performance * 100).toFixed(1)}%` : "—"}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

const th = {
  padding: "10px 14px",
  borderBottom: "2px solid #d1d5db",
  textAlign: "left" as const,
  whiteSpace: "nowrap" as const,
}
const td = { padding: "8px 12px" }
