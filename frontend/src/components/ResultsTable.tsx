import { Row, RouterRow } from "../api/client"

type Props = {
  rows: Row[]
}

function formatParams(params: RouterRow["params"]): string {
  return Object.entries(params)
    .map(([k, v]) => `${k}: ${v}`)
    .join(" | ")
}

export default function ResultsTable({ rows }: Props) {
  if (rows.length === 0) return <p>No data available.</p>

  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
        <thead>
          <tr style={{ background: "#f0f0f0", textAlign: "left" }}>
            <th style={th}>Type</th>
            <th style={th}>Name</th>
            <th style={th}>Eval</th>
            <th style={th}>Performance</th>
            <th style={th}>Total Cost ($)</th>
            <th style={th}>Params</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} style={{ borderBottom: "1px solid #e0e0e0" }}>
              <td style={td}>
                <span style={{
                  padding: "2px 8px",
                  borderRadius: 4,
                  background: row.type === "llm" ? "#dbeafe" : "#dcfce7",
                  color: row.type === "llm" ? "#1d4ed8" : "#15803d",
                  fontSize: 12,
                }}>
                  {row.type === "llm" ? "LLM" : row.router_type.toUpperCase()}
                </span>
              </td>
              <td style={td}>
                {row.type === "llm" ? row.model_name : row.router_type}
              </td>
              <td style={td}>{row.eval_name}</td>
              <td style={td}>{(row.performance * 100).toFixed(1)}%</td>
              <td style={td}>${row.total_cost.toFixed(4)}</td>
              <td style={{ ...td, color: "#6b7280", fontSize: 12 }}>
                {row.type === "router" ? formatParams(row.params) : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const th = {
  padding: "10px 14px",
  borderBottom: "2px solid #d1d5db",
  fontWeight: 600,
  whiteSpace: "nowrap",
}

const td = {
  padding: "8px 14px",
  verticalAlign: "top",
}
