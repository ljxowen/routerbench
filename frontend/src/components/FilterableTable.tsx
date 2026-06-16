import { useState } from "react"
import { Row, RouterRow } from "../api/client"

type Props = { rows: Row[]; evalNames: string[] }
type SortKey = "eval_name" | "type" | "performance" | "total_cost"
type SortDir = "asc" | "desc"

const COL_LABELS: Record<SortKey, string> = {
  type: "Type",
  eval_name: "Benchmark",
  performance: "Performance",
  total_cost: "Cost ($)",
}

function formatParams(params: RouterRow["params"]): string {
  return Object.entries(params)
    .map(([k, v]) => `${k}: ${v}`)
    .join(" · ")
}

export default function FilterableTable({ rows, evalNames }: Props) {
  const [evalFilter, setEvalFilter] = useState("")
  const [typeFilter, setTypeFilter] = useState("")
  const [sortKey, setSortKey] = useState<SortKey>("performance")
  const [sortDir, setSortDir] = useState<SortDir>("desc")

  const types = Array.from(
    new Set(rows.map((r) => (r.type === "llm" ? "llm" : r.router_type)))
  ).sort()

  function handleSort(key: SortKey) {
    if (key === sortKey) setSortDir((d) => (d === "asc" ? "desc" : "asc"))
    else { setSortKey(key); setSortDir("desc") }
  }

  const filtered = rows
    .filter((r) => !evalFilter || r.eval_name === evalFilter)
    .filter((r) => !typeFilter || (r.type === "llm" ? "llm" : r.router_type) === typeFilter)
    .sort((a, b) => {
      let av: string | number, bv: string | number
      if (sortKey === "eval_name") { av = a.eval_name; bv = b.eval_name }
      else if (sortKey === "type") { av = a.type; bv = b.type }
      else if (sortKey === "performance") { av = a.performance; bv = b.performance }
      else { av = a.total_cost; bv = b.total_cost }
      if (av < bv) return sortDir === "asc" ? -1 : 1
      if (av > bv) return sortDir === "asc" ? 1 : -1
      return 0
    })

  return (
    <div>
      <div style={{ display: "flex", gap: 12, marginBottom: 16, flexWrap: "wrap" }}>
        <select value={evalFilter} onChange={(e) => setEvalFilter(e.target.value)} style={sel}>
          <option value="">All Benchmarks</option>
          {evalNames.map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
        <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)} style={sel}>
          <option value="">All Types</option>
          {types.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <span style={{ color: "#6b7280", fontSize: 13, alignSelf: "center" }}>
          {filtered.length} rows
        </span>
      </div>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: "#f3f4f6" }}>
              {(["type", "eval_name", "performance", "total_cost"] as SortKey[]).map((key) => (
                <th key={key} style={{ ...th, cursor: "pointer" }} onClick={() => handleSort(key)}>
                  {COL_LABELS[key]}
                  {sortKey === key ? (sortDir === "asc" ? " ↑" : " ↓") : ""}
                </th>
              ))}
              <th style={th}>Name</th>
              <th style={th}>Params</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((row, i) => (
              <tr key={i} style={{ borderBottom: "1px solid #e5e7eb" }}>
                <td style={td}>
                  <span style={{
                    padding: "2px 8px", borderRadius: 4, fontSize: 11,
                    background: row.type === "llm" ? "#dbeafe" : "#dcfce7",
                    color: row.type === "llm" ? "#1d4ed8" : "#15803d",
                  }}>
                    {row.type === "llm" ? "LLM" : row.router_type.toUpperCase()}
                  </span>
                </td>
                <td style={td}>{row.eval_name}</td>
                <td style={{ ...td, fontWeight: 500 }}>{(row.performance * 100).toFixed(1)}%</td>
                <td style={td}>${row.total_cost.toFixed(4)}</td>
                <td style={td}>{row.type === "llm" ? row.model_name : row.router_type}</td>
                <td style={{ ...td, color: "#6b7280", fontSize: 11 }}>
                  {row.type === "router" ? formatParams(row.params) : "—"}
                </td>
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
const sel = { padding: "6px 10px", borderRadius: 4, border: "1px solid #d1d5db", fontSize: 13 }
