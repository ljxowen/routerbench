import { useEffect, useState } from "react"
import { Row, fetchEvalNames, fetchResults } from "./api/client"
import SummaryTable from "./components/SummaryTable"
import FilterableTable from "./components/FilterableTable"
import ComparisonTable from "./components/ComparisonTable"
import HeatmapTable from "./components/HeatmapTable"
import PerformanceCostChart from "./components/PerformanceCostChart"
import RouteExplorer from "./components/RouteExplorer"
import "./App.css"

type Page = "summary" | "details" | "comparison" | "heatmap" | "chart" | "route"

const TABS: { id: Page; label: string }[] = [
  { id: "summary", label: "Summary" },
  { id: "details", label: "Details" },
  { id: "comparison", label: "Comparison" },
  { id: "heatmap", label: "Heatmap" },
  { id: "chart", label: "Chart" },
  { id: "route", label: "Route a Task" },
]

export default function App() {
  const [page, setPage] = useState<Page>("summary")
  const [evalNames, setEvalNames] = useState<string[]>([])
  const [rows, setRows] = useState<Row[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([fetchEvalNames(), fetchResults()])
      .then(([names, data]) => {
        setEvalNames(names)
        setRows(data)
      })
      .catch(() => setError("Failed to load data"))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div style={{ maxWidth: 1400, margin: "0 auto", padding: "24px 16px" }}>
      <h1 style={{ marginBottom: 16 }}>RouterBench Results</h1>
      <div style={{ display: "flex", gap: 4, marginBottom: 24, borderBottom: "2px solid #e5e7eb" }}>
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setPage(tab.id)}
            style={{
              padding: "8px 20px",
              border: "none",
              borderBottom: page === tab.id ? "2px solid #2563eb" : "2px solid transparent",
              background: "none",
              cursor: "pointer",
              fontWeight: page === tab.id ? 600 : 400,
              color: page === tab.id ? "#2563eb" : "#374151",
              marginBottom: -2,
              fontSize: 14,
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>
      {/* Live routing is independent of the precomputed benchmark data, so it
          renders even while that data loads or if it failed to load. */}
      {page === "route" && <RouteExplorer />}
      {page !== "route" && (
        <>
          {loading && <p style={{ color: "#6b7280" }}>Loading...</p>}
          {error && <p style={{ color: "red" }}>{error}</p>}
          {!loading && !error && (
            <>
              {page === "summary" && <SummaryTable rows={rows} />}
              {page === "details" && <FilterableTable rows={rows} evalNames={evalNames} />}
              {page === "comparison" && <ComparisonTable rows={rows} evalNames={evalNames} />}
              {page === "heatmap" && <HeatmapTable rows={rows} />}
              {page === "chart" && <PerformanceCostChart evalNames={evalNames} />}
            </>
          )}
        </>
      )}
    </div>
  )
}
