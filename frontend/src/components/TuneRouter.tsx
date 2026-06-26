import { useEffect, useRef, useState } from "react"
import {
  TuningStatus,
  TuningMetrics,
  TuningSchema,
  fetchTuningSchema,
  getTuningStatus,
  startTuning,
} from "../api/client"

// Router-tuning tab. The user uploads their own labeled data (a CSV with a
// `prompt` column plus one 0/1 correctness column per candidate model) and we
// fit a router set tailored to their task distribution. Fitting runs async in a
// background worker, so we kick it off then poll for status + the held-out
// quality report. Once it succeeds, the set is selectable by name on the
// "Route a Task" tab.

const ROUTER_TYPES = ["knn", "mlp", "svm"]
const POLL_MS = 2000
const TERMINAL = new Set(["succeeded", "failed"])

function pct(v: number): string {
  return `${(v * 100).toFixed(1)}%`
}

// The two models shown in the inline example (any recognized ids would do).
const EXAMPLE_MODELS = ["gpt-4-1106-preview", "gpt-3.5-turbo-1106"]

// Cell styles for the rendered example table.
const exHeadCell: React.CSSProperties = {
  padding: "4px 10px",
  textAlign: "left",
  borderBottom: "1px solid #bfdbfe",
  whiteSpace: "nowrap",
}
const exCell: React.CSSProperties = {
  padding: "4px 10px",
  borderBottom: "1px solid #eff6ff",
  whiteSpace: "nowrap",
}

// Canonical column order used by BOTH the example and the downloaded template:
// prompt, one correctness column per model, then optional eval_name. (Order does
// not actually matter — columns are matched by header name — but we keep it
// consistent so the docs, example, and template agree.)
type ExampleRow = { prompt: string; evalName: string; fill: (m: string) => string }

function csvCell(v: string): string {
  // Quote anything with a comma/quote/space so the example is valid CSV.
  return /[",\s]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v
}

function buildCsv(models: string[], rows: ExampleRow[]): string {
  const header = ["prompt", ...models, "eval_name"].join(",")
  const line = (r: ExampleRow) =>
    [csvCell(r.prompt), ...models.map(r.fill), r.evalName].join(",")
  return [header, ...rows.map(line)].join("\n") + "\n"
}

// Inline example rows. The blank gpt-3.5 cell on row 2 demonstrates "this model
// was not evaluated on this prompt".
const EXAMPLE_ROWS: ExampleRow[] = [
  { prompt: "What is 2+2?", evalName: "math", fill: () => "1" },
  {
    prompt: "Write a haiku about the sea",
    evalName: "creative",
    fill: (m) => (m.includes("gpt-4") ? "1" : ""),
  },
  { prompt: "Prove the Riemann hypothesis", evalName: "math", fill: () => "0" },
]

// Download a ready-to-fill template: the same columns as the example, but with a
// correctness column for every recognized model (delete the ones you don't have).
function downloadTemplate(models: string[]) {
  const rows: ExampleRow[] = [
    { prompt: "What is 2+2?", evalName: "math", fill: () => "1" },
    { prompt: "Prove the Riemann hypothesis", evalName: "math", fill: () => "0" },
  ]
  const blob = new Blob([buildCsv(models, rows)], { type: "text/csv" })
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = "routerbench_tuning_template.csv"
  a.click()
  URL.revokeObjectURL(url)
}

function FormatHelp({ schema }: { schema: TuningSchema | null }) {
  const [showModels, setShowModels] = useState(false)
  const code: React.CSSProperties = {
    background: "#dbeafe",
    padding: "1px 5px",
    borderRadius: 3,
    fontFamily: "monospace",
  }
  return (
    <div
      style={{
        background: "#eff6ff",
        border: "1px solid #bfdbfe",
        borderRadius: 8,
        padding: "12px 14px",
        marginBottom: 20,
        fontSize: 13,
        color: "#1e3a8a",
        lineHeight: 1.6,
      }}
    >
      <div style={{ fontWeight: 600, marginBottom: 6 }}>
        Columns (these column types, in any order)
      </div>
      <table
        style={{
          borderCollapse: "collapse",
          width: "100%",
          marginBottom: 8,
          fontSize: 12.5,
        }}
      >
        <thead>
          <tr style={{ textAlign: "left", borderBottom: "1px solid #bfdbfe" }}>
            <th style={{ padding: "4px 10px 4px 0" }}>Column</th>
            <th style={{ padding: "4px 10px" }}>Required</th>
            <th style={{ padding: "4px 10px" }}>Value</th>
          </tr>
        </thead>
        <tbody>
          <tr style={{ borderBottom: "1px solid #dbeafe" }}>
            <td style={{ padding: "4px 10px 4px 0" }}>
              <span style={code}>prompt</span>
            </td>
            <td style={{ padding: "4px 10px" }}>yes</td>
            <td style={{ padding: "4px 10px" }}>the task text</td>
          </tr>
          <tr style={{ borderBottom: "1px solid #dbeafe" }}>
            <td style={{ padding: "4px 10px 4px 0" }}>
              <span style={code}>&lt;model-id&gt;</span>
              <div style={{ color: "#64748b", fontSize: 11 }}>
                one column per model (≥{schema?.min_models ?? 2})
              </div>
            </td>
            <td style={{ padding: "4px 10px" }}>yes</td>
            <td style={{ padding: "4px 10px" }}>
              the header is the exact id of a model you route among (e.g.{" "}
              <span style={code}>gpt-4-1106-preview</span> — see the list below);
              value <span style={code}>1</span> = it got the prompt right,{" "}
              <span style={code}>0</span> = wrong, blank = not evaluated.
            </td>
          </tr>
          <tr style={{ borderBottom: "1px solid #dbeafe" }}>
            <td style={{ padding: "4px 10px 4px 0" }}>
              <span style={code}>&lt;model-id&gt;|model_response</span>
            </td>
            <td style={{ padding: "4px 10px" }}>optional</td>
            <td style={{ padding: "4px 10px" }}>
              a sample answer; improves cost estimates
            </td>
          </tr>
          <tr>
            <td style={{ padding: "4px 10px 4px 0" }}>
              <span style={code}>eval_name</span>
            </td>
            <td style={{ padding: "4px 10px" }}>optional</td>
            <td style={{ padding: "4px 10px" }}>
              groups rows into benchmarks (default: the set name)
            </td>
          </tr>
        </tbody>
      </table>
      <div style={{ marginBottom: 8 }}>
        Column order doesn’t matter (matched by header name).
        {schema && (
          <>
            {" "}
            Need ≥<strong>{schema.min_rows}</strong> rows and ≥
            <strong>{schema.min_labels_per_model}</strong> labels per model.
          </>
        )}
      </div>
      <div style={{ marginBottom: 8 }}>
        <strong>Example</strong> — here the two <span style={code}>&lt;model-id&gt;</span>{" "}
        columns are filled in with real ids,{" "}
        <span style={code}>gpt-4-1106-preview</span> (GPT-4) and{" "}
        <span style={code}>gpt-3.5-turbo-1106</span> (GPT-3.5), and{" "}
        <span style={code}>eval_name</span> is last:
        <div style={{ overflowX: "auto", marginTop: 4 }}>
          <table
            style={{
              borderCollapse: "collapse",
              fontSize: 12,
              fontFamily: "monospace",
              border: "1px solid #bfdbfe",
            }}
          >
            <thead>
              <tr style={{ background: "#dbeafe" }}>
                <th style={exHeadCell}>prompt</th>
                {EXAMPLE_MODELS.map((m) => (
                  <th key={m} style={exHeadCell}>
                    {m}
                  </th>
                ))}
                <th style={exHeadCell}>eval_name</th>
              </tr>
            </thead>
            <tbody>
              {EXAMPLE_ROWS.map((r, i) => (
                <tr key={i}>
                  <td style={exCell}>{r.prompt}</td>
                  {EXAMPLE_MODELS.map((m) => {
                    const v = r.fill(m)
                    return (
                      <td
                        key={m}
                        style={{ ...exCell, textAlign: "center" }}
                        title={v === "" ? "blank = not evaluated on this prompt" : ""}
                      >
                        {v === "" ? (
                          <span style={{ color: "#94a3b8" }}>— blank</span>
                        ) : (
                          v
                        )}
                      </td>
                    )
                  })}
                  <td style={exCell}>{r.evalName}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div style={{ color: "#64748b", fontSize: 11.5, marginTop: 3 }}>
          (each row = one prompt; <span style={code}>1</span>/<span style={code}>0</span>{" "}
          = that model got it right/wrong; a blank cell = that model wasn’t evaluated
          on that prompt. The downloaded template has these exact columns.)
        </div>
      </div>
      <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
        {schema && (
          <button
            type="button"
            onClick={() => downloadTemplate(schema.recognized_models)}
            style={{
              padding: "4px 12px",
              border: "1px solid #2563eb",
              background: "white",
              color: "#2563eb",
              borderRadius: 6,
              cursor: "pointer",
              fontSize: 13,
            }}
          >
            ⬇ Download CSV template
          </button>
        )}
        {schema && (
          <button
            type="button"
            onClick={() => setShowModels((s) => !s)}
            style={{
              padding: "4px 12px",
              border: "none",
              background: "none",
              color: "#2563eb",
              cursor: "pointer",
              fontSize: 13,
              textDecoration: "underline",
            }}
          >
            {showModels ? "Hide" : "Show"} the {schema.recognized_models.length}{" "}
            valid model headers
          </button>
        )}
      </div>
      {showModels && schema && (
        <div
          style={{
            marginTop: 8,
            maxHeight: 160,
            overflowY: "auto",
            background: "white",
            border: "1px solid #bfdbfe",
            borderRadius: 6,
            padding: "6px 10px",
          }}
        >
          {schema.recognized_models.map((m) => (
            <div key={m} style={{ fontFamily: "monospace", fontSize: 12 }}>
              {m}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function QualityReport({ metrics }: { metrics: TuningMetrics }) {
  return (
    <div style={{ marginTop: 16 }}>
      <h3 style={{ marginBottom: 8 }}>Held-out quality</h3>
      <p style={{ color: "#6b7280", fontSize: 13, marginTop: 0 }}>
        Evaluated on {metrics.eval_rows} held-out rows ({metrics.train_rows} used
        for training). A router helps when its accuracy beats the best single
        model and approaches the oracle.
      </p>
      <div style={{ display: "flex", gap: 24, marginBottom: 12, fontSize: 14 }}>
        <div>
          <div style={{ color: "#6b7280" }}>Best single model</div>
          <div style={{ fontWeight: 600 }}>
            {metrics.best_single_model} — {pct(metrics.best_single_accuracy)}
          </div>
        </div>
        <div>
          <div style={{ color: "#6b7280" }}>Oracle (upper bound)</div>
          <div style={{ fontWeight: 600 }}>{pct(metrics.oracle_accuracy)}</div>
        </div>
      </div>
      <table style={{ borderCollapse: "collapse", fontSize: 14 }}>
        <thead>
          <tr style={{ textAlign: "left", borderBottom: "2px solid #e5e7eb" }}>
            <th style={{ padding: "6px 16px 6px 0" }}>Router</th>
            <th style={{ padding: "6px 16px" }}>Routed accuracy</th>
            <th style={{ padding: "6px 16px" }}>vs. best single</th>
            <th style={{ padding: "6px 16px" }}>Est. cost (split)</th>
          </tr>
        </thead>
        <tbody>
          {metrics.routers.map((r) => {
            const delta = r.routed_accuracy - metrics.best_single_accuracy
            return (
              <tr key={r.router_type} style={{ borderBottom: "1px solid #f3f4f6" }}>
                <td style={{ padding: "6px 16px 6px 0", fontWeight: 600 }}>
                  {r.router_type.toUpperCase()}
                </td>
                <td style={{ padding: "6px 16px" }}>{pct(r.routed_accuracy)}</td>
                <td
                  style={{
                    padding: "6px 16px",
                    color: delta >= 0 ? "#16a34a" : "#dc2626",
                  }}
                >
                  {delta >= 0 ? "+" : ""}
                  {pct(delta)}
                </td>
                <td style={{ padding: "6px 16px" }}>${r.routed_cost.toFixed(4)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export default function TuneRouter() {
  const [file, setFile] = useState<File | null>(null)
  const [datasetName, setDatasetName] = useState("")
  const [types, setTypes] = useState<string[]>(ROUTER_TYPES)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<TuningStatus | null>(null)
  const [schema, setSchema] = useState<TuningSchema | null>(null)
  const pollRef = useRef<number | null>(null)

  // Load the upload contract (valid model headers + size rules) once, so the
  // format guidance and the template stay in sync with the server.
  useEffect(() => {
    fetchTuningSchema()
      .then(setSchema)
      .catch(() => setSchema(null))
  }, [])

  // Poll the job until it reaches a terminal state, then stop.
  useEffect(() => {
    if (!status || TERMINAL.has(status.status)) return
    pollRef.current = window.setTimeout(async () => {
      try {
        setStatus(await getTuningStatus(status.job_id))
      } catch {
        /* transient; the next tick retries */
        setStatus({ ...status })
      }
    }, POLL_MS)
    return () => {
      if (pollRef.current) window.clearTimeout(pollRef.current)
    }
  }, [status])

  function toggleType(t: string) {
    setTypes((prev) =>
      prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t],
    )
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    if (!file) return setError("Choose a CSV file to upload.")
    if (!datasetName.trim()) return setError("Give the router set a name.")
    if (types.length === 0) return setError("Select at least one router type.")
    setSubmitting(true)
    setStatus(null)
    try {
      const res = await startTuning(file, datasetName.trim(), types)
      // Seed the poller with a pending status carrying the job_id.
      setStatus({
        job_id: res.job_id,
        dataset_name: res.dataset_name,
        status: res.status,
        error: "",
        run_id: "",
        router_types: types,
        metrics: null,
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start tuning")
    } finally {
      setSubmitting(false)
    }
  }

  const running =
    status !== null && !TERMINAL.has(status.status)

  return (
    <div style={{ maxWidth: 760 }}>
      <FormatHelp schema={schema} />

      <form onSubmit={onSubmit}>
        <label style={{ display: "block", marginBottom: 12 }}>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>Training data (CSV)</div>
          <input
            type="file"
            accept=".csv,text/csv"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </label>

        <label style={{ display: "block", marginBottom: 12 }}>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>Router set name</div>
          <input
            type="text"
            value={datasetName}
            placeholder="e.g. support-tickets"
            onChange={(e) => setDatasetName(e.target.value)}
            style={{ padding: "6px 10px", width: 280, fontSize: 14 }}
          />
        </label>

        <div style={{ marginBottom: 16 }}>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>Router types</div>
          {ROUTER_TYPES.map((t) => (
            <label key={t} style={{ marginRight: 16, fontSize: 14 }}>
              <input
                type="checkbox"
                checked={types.includes(t)}
                onChange={() => toggleType(t)}
              />{" "}
              {t.toUpperCase()}
            </label>
          ))}
        </div>

        <button
          type="submit"
          disabled={submitting || running}
          style={{
            padding: "8px 20px",
            background: submitting || running ? "#9ca3af" : "#2563eb",
            color: "white",
            border: "none",
            borderRadius: 6,
            cursor: submitting || running ? "default" : "pointer",
            fontSize: 14,
            fontWeight: 600,
          }}
        >
          {running ? "Tuning…" : submitting ? "Submitting…" : "Tune router set"}
        </button>
      </form>

      {error && <p style={{ color: "#dc2626", marginTop: 12 }}>{error}</p>}

      {status && (
        <div style={{ marginTop: 20 }}>
          <div style={{ fontSize: 14 }}>
            Job <code>{status.job_id.slice(0, 8)}</code> for set{" "}
            <strong>{status.dataset_name}</strong>:{" "}
            <span
              style={{
                fontWeight: 600,
                color:
                  status.status === "succeeded"
                    ? "#16a34a"
                    : status.status === "failed"
                      ? "#dc2626"
                      : "#2563eb",
              }}
            >
              {status.status}
            </span>
            {running && " — this can take a minute (embedding + fitting)…"}
          </div>
          {status.status === "failed" && status.error && (
            <p style={{ color: "#dc2626", marginTop: 8 }}>{status.error}</p>
          )}
          {status.status === "succeeded" && status.metrics && (
            <>
              <QualityReport metrics={status.metrics} />
              <p style={{ color: "#16a34a", marginTop: 12, fontSize: 14 }}>
                ✓ Router set <strong>{status.dataset_name}</strong> is ready —
                select it on the <strong>Route a Task</strong> tab.
              </p>
            </>
          )}
        </div>
      )}
    </div>
  )
}
