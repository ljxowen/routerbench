import { useEffect, useState } from "react"
import {
  RouteResponse,
  RouterDecision,
  ModelScore,
  RouterSet,
  fetchRouterSets,
  routeTask,
} from "../api/client"

// Live single-prompt routing tab. The user types a task; each router predicts
// how every candidate model would do and returns its pick plus the full ranking.
// Everything shown is a prediction/estimate — see the banner — because the LLM
// is not actually called.

// willingness_to_pay (wtp) values must land in the narrow band where the router's
// cost term actually competes with predicted performance. The router scores models
// as `performance * wtp - per_token_cost`, and that cost penalty is a fixed, tiny
// per-token rate (~1e-6..1e-5): so for wtp >= ~1e-4 performance dominates and the
// ranking is identical regardless of the value (which is why 0/1/100/10000 all
// looked the same). Cost only bites at SMALL wtp — smaller wtp = cheaper picks.
// wtp=0 is the special "no cost adjustment" (pure accuracy) mode. The exact band
// is dataset/cost-scale dependent; these values were tuned against the routerbench
// cost table. (For a monotonic, dataset-independent knob, see the `performance -
// lambda * estimated_cost` model discussed in PROJECT_GUIDE / the live-routing notes.)
const WTP_OPTIONS = [
  { label: "Max accuracy (ignore cost)", value: 0 },
  { label: "Mostly accuracy", value: 1e-5 },
  { label: "Favor cheaper", value: 1e-6 },
  { label: "Cheapest", value: 1e-8 },
]

function fmtWtp(v: number): string {
  return v === 0 ? "0" : v.toExponential(0)
}

function fmtPerf(p: number): string {
  // Predicted performance is an expected-accuracy estimate; SVR can stray a
  // little outside [0, 1], so show the raw value but keep it readable.
  return `${(p * 100).toFixed(1)}%`
}

function fmtCost(c: number): string {
  if (c === 0) return "—"
  if (c < 0.01) return `$${c.toExponential(2)}`
  return `$${c.toFixed(4)}`
}

function RankingTable({ ranking }: { ranking: ModelScore[] }) {
  return (
    <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 13 }}>
      <thead>
        <tr style={{ textAlign: "left", color: "#6b7280" }}>
          <th style={{ padding: "6px 8px" }}>#</th>
          <th style={{ padding: "6px 8px" }}>Model</th>
          <th style={{ padding: "6px 8px", textAlign: "right" }}>Pred. performance</th>
          <th style={{ padding: "6px 8px", textAlign: "right" }}>Est. cost</th>
        </tr>
      </thead>
      <tbody>
        {ranking.map((s) => (
          <tr
            key={s.model_name}
            style={{
              borderTop: "1px solid #f0f0f0",
              background: s.rank === 1 ? "#eff6ff" : "transparent",
              fontWeight: s.rank === 1 ? 600 : 400,
            }}
          >
            <td style={{ padding: "6px 8px", color: "#9ca3af" }}>{s.rank}</td>
            <td style={{ padding: "6px 8px" }}>{s.display_name}</td>
            <td style={{ padding: "6px 8px", textAlign: "right" }}>
              {fmtPerf(s.predicted_performance)}
            </td>
            <td style={{ padding: "6px 8px", textAlign: "right" }}>
              {fmtCost(s.estimated_cost)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function DecisionCard({ decision }: { decision: RouterDecision }) {
  return (
    <div
      style={{
        border: "1px solid #e5e7eb",
        borderRadius: 8,
        padding: 16,
        minWidth: 320,
        flex: "1 1 320px",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <h3 style={{ margin: 0, textTransform: "uppercase" }}>{decision.router_type}</h3>
        {decision.best_model_display && (
          <span style={{ fontSize: 13, color: "#6b7280" }}>
            picks <strong style={{ color: "#2563eb" }}>{decision.best_model_display}</strong>
          </span>
        )}
      </div>
      {decision.note ? (
        <p style={{ color: "#b45309", fontSize: 13, marginTop: 12 }}>{decision.note}</p>
      ) : (
        <div style={{ marginTop: 12 }}>
          <RankingTable ranking={decision.ranking} />
        </div>
      )}
    </div>
  )
}

export default function RouteExplorer() {
  const [prompt, setPrompt] = useState("")
  const [wtp, setWtp] = useState(0)
  // Empty = the default global router set; a name routes with a tuned set (see
  // the Tune Router tab).
  const [routerSet, setRouterSet] = useState("")
  const [routerSets, setRouterSets] = useState<RouterSet[]>([])
  const [result, setResult] = useState<RouteResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Load the selectable router sets once (default + any tuned sets). Switching
  // back to this tab remounts the component, so a freshly tuned set shows up.
  useEffect(() => {
    fetchRouterSets()
      .then(setRouterSets)
      .catch(() => setRouterSets([]))
  }, [])

  async function onSubmit() {
    if (!prompt.trim()) return
    setLoading(true)
    setError(null)
    try {
      setResult(await routeTask(prompt, wtp, undefined, routerSet))
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to route prompt")
      setResult(null)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <div
        style={{
          background: "#fffbeb",
          border: "1px solid #fde68a",
          borderRadius: 6,
          padding: "8px 12px",
          fontSize: 13,
          color: "#92400e",
          marginBottom: 16,
        }}
      >
        Numbers below are router <strong>predictions</strong> and <strong>cost estimates</strong>{" "}
        for your prompt — the models are not actually called.
      </div>

      <textarea
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        placeholder="Enter a task or question to route…"
        rows={4}
        style={{
          width: "100%",
          padding: 12,
          fontSize: 14,
          border: "1px solid #d1d5db",
          borderRadius: 6,
          boxSizing: "border-box",
          resize: "vertical",
        }}
      />

      <div style={{ display: "flex", gap: 12, alignItems: "center", marginTop: 12 }}>
        <label style={{ fontSize: 13, color: "#374151" }}>
          Cost sensitivity:{" "}
          <select
            value={wtp}
            onChange={(e) => setWtp(Number(e.target.value))}
            style={{ padding: "4px 8px", fontSize: 13 }}
          >
            {WTP_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label} — wtp={fmtWtp(o.value)}
              </option>
            ))}
          </select>{" "}
          <span style={{ color: "#9ca3af" }}>(wtp={fmtWtp(wtp)})</span>
        </label>
        <label style={{ fontSize: 13, color: "#374151" }}>
          Router set:{" "}
          <select
            value={routerSet}
            onChange={(e) => setRouterSet(e.target.value)}
            style={{ padding: "4px 8px", fontSize: 13 }}
          >
            {/* Default global set, plus any tuned sets (non-default ones). */}
            <option value="">default</option>
            {routerSets
              .filter((s) => !s.is_default)
              .map((s) => (
                <option key={s.name} value={s.name}>
                  {s.name} ({s.router_types.join("/")})
                </option>
              ))}
          </select>
        </label>
        <button
          onClick={onSubmit}
          disabled={loading || !prompt.trim()}
          style={{
            padding: "8px 20px",
            background: loading || !prompt.trim() ? "#9ca3af" : "#2563eb",
            color: "white",
            border: "none",
            borderRadius: 6,
            cursor: loading || !prompt.trim() ? "default" : "pointer",
            fontSize: 14,
          }}
        >
          {loading ? "Routing…" : "Route"}
        </button>
      </div>

      {error && <p style={{ color: "red", marginTop: 16 }}>{error}</p>}

      {result && (
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: 16,
            marginTop: 24,
          }}
        >
          {result.decisions.map((d) => (
            <DecisionCard key={d.router_type} decision={d} />
          ))}
        </div>
      )}
    </div>
  )
}
