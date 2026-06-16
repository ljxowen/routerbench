import { Row } from "../api/client"

type Props = { rows: Row[] }
type Cell = { performance: number; total_cost: number }

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

export default function SummaryTable({ rows }: Props) {
  const { evalNames, modelNames, grid } = buildGrid(rows)

  return (
    <div>
      <p style={{ marginBottom: 12, fontSize: 13, color: "#6b7280" }}>
        Best performance per benchmark × model. Each cell shows accuracy and total cost.
      </p>
      <div style={{ overflowX: "auto" }}>
        <table style={{ borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: "#f3f4f6" }}>
              <th style={th}>Benchmark</th>
              {modelNames.map((m) => (
                <th key={m} style={{ ...th, minWidth: 120 }}>{m}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {evalNames.map((evalName) => (
              <tr key={evalName} style={{ borderBottom: "1px solid #e5e7eb" }}>
                <td style={{ ...td, fontWeight: 500, whiteSpace: "nowrap" }}>{evalName}</td>
                {modelNames.map((m) => {
                  const cell = grid[evalName]?.[m]
                  return (
                    <td key={m} style={td}>
                      {cell ? (
                        <>
                          <div style={{ fontWeight: 500 }}>{(cell.performance * 100).toFixed(1)}%</div>
                          <div style={{ color: "#6b7280", fontSize: 11 }}>${cell.total_cost.toFixed(3)}</div>
                        </>
                      ) : "—"}
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
const td = { padding: "8px 14px" }
