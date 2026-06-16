import { useState } from "react"
import { Row } from "../api/client"

type Props = { rows: Row[]; evalNames: string[] }
type ModelData = { name: string; type: "llm" | "router"; performance: number; total_cost: number }

export default function ComparisonTable({ rows, evalNames }: Props) {
  const [selectedEval, setSelectedEval] = useState(evalNames[0] ?? "")

  const evalRows = rows.filter((r) => r.eval_name === selectedEval)

  const llms: ModelData[] = evalRows
    .filter((r) => r.type === "llm")
    .map((r) => ({
      name: r.type === "llm" ? r.model_name : "",
      type: "llm",
      performance: r.performance,
      total_cost: r.total_cost,
    }))

  const routerMap: Record<string, ModelData> = {}
  for (const r of evalRows) {
    if (r.type !== "router") continue
    const cur = routerMap[r.router_type]
    if (!cur || r.performance > cur.performance) {
      routerMap[r.router_type] = {
        name: r.router_type,
        type: "router",
        performance: r.performance,
        total_cost: r.total_cost,
      }
    }
  }

  const cheapestLLM = llms.length > 0
    ? llms.reduce((min, l) => l.total_cost < min.total_cost ? l : min)
    : null

  const all = [...llms, ...Object.values(routerMap)].sort((a, b) => b.performance - a.performance)

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
        <label style={{ fontWeight: 500, fontSize: 13 }}>Benchmark:</label>
        <select
          value={selectedEval}
          onChange={(e) => setSelectedEval(e.target.value)}
          style={{ padding: "6px 10px", borderRadius: 4, border: "1px solid #d1d5db", fontSize: 13 }}
        >
          {evalNames.map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
      </div>
      <div style={{ overflowX: "auto" }}>
        <table style={{ borderCollapse: "collapse", fontSize: 13, width: "100%" }}>
          <thead>
            <tr style={{ background: "#f3f4f6" }}>
              <th style={th}>Name</th>
              <th style={th}>Type</th>
              <th style={th}>Performance</th>
              <th style={th}>Total Cost ($)</th>
              <th style={th}>vs Cheapest LLM</th>
            </tr>
          </thead>
          <tbody>
            {all.map((item, i) => {
              const saving = cheapestLLM
                ? ((cheapestLLM.total_cost - item.total_cost) / cheapestLLM.total_cost) * 100
                : null
              return (
                <tr key={i} style={{
                  borderBottom: "1px solid #e5e7eb",
                  background: item.type === "router" ? "#f0fdf4" : "white",
                }}>
                  <td style={{ ...td, fontWeight: 500 }}>{item.name}</td>
                  <td style={td}>
                    <span style={{
                      padding: "2px 8px", borderRadius: 4, fontSize: 11,
                      background: item.type === "llm" ? "#dbeafe" : "#dcfce7",
                      color: item.type === "llm" ? "#1d4ed8" : "#15803d",
                    }}>
                      {item.type === "llm" ? "LLM" : "Router"}
                    </span>
                  </td>
                  <td style={{ ...td, fontWeight: 500 }}>{(item.performance * 100).toFixed(1)}%</td>
                  <td style={td}>${item.total_cost.toFixed(4)}</td>
                  <td style={{
                    ...td,
                    color: saving === null ? "#6b7280" : saving > 0 ? "#15803d" : saving < 0 ? "#b91c1c" : "#6b7280",
                    fontWeight: saving !== null && Math.abs(saving) > 5 ? 600 : 400,
                  }}>
                    {saving === null ? "—" : `${saving > 0 ? "−" : "+"}${Math.abs(saving).toFixed(1)}%`}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
        {cheapestLLM && (
          <p style={{ marginTop: 10, fontSize: 12, color: "#6b7280" }}>
            * Cost compared against cheapest LLM: <strong>{cheapestLLM.name}</strong> (${cheapestLLM.total_cost.toFixed(4)})
          </p>
        )}
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
