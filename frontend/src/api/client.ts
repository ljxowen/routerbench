export type RouterRow = {
  type: "router"
  router_type: string
  eval_name: string
  performance: number
  total_cost: number
  params: Record<string, string | number>
}

export type LLMRow = {
  type: "llm"
  router_type: "llm"
  model_name: string
  eval_name: string
  performance: number
  total_cost: number
}

export type Row = RouterRow | LLMRow

export async function fetchEvalNames(): Promise<string[]> {
  const res = await fetch("/api/evals")
  if (!res.ok) throw new Error("Failed to fetch eval names")
  const data = await res.json()
  return data.eval_names
}

export async function fetchResults(evalName?: string): Promise<Row[]> {
  const url = evalName
    ? `/api/results?eval_name=${encodeURIComponent(evalName)}`
    : "/api/results"
  const res = await fetch(url)
  if (!res.ok) throw new Error("Failed to fetch results")
  const data = await res.json()
  return data.rows
}

// ---- Chart data (matches the offline matplotlib visualizer) ----

export type ChartPoint = { total_cost: number; performance: number }

export type ChartRouter = {
  name: string // legend name, e.g. "MLP router"
  display: string // short label, e.g. "MLP"
  points: ChartPoint[] // willingness-to-pay sweep
  ndch: ChartPoint[] // non-decreasing convex hull (frontier)
}

export type ChartLLM = {
  model_name: string
  display: string
  total_cost: number
  performance: number
}

export type ChartData = {
  eval_name: string
  routers: ChartRouter[]
  llms: ChartLLM[]
  oracle: ChartPoint | null
  zero_router_ndch: ChartPoint[]
}

export async function fetchChartData(evalName: string): Promise<ChartData> {
  const res = await fetch(`/api/chart?eval_name=${encodeURIComponent(evalName)}`)
  if (!res.ok) throw new Error("Failed to fetch chart data")
  return res.json()
}

// ---- Live single-prompt routing (/api/route) ----
//
// Unlike the data above (precomputed benchmark *measurements*), these are router
// *predictions* for a brand-new prompt: predicted_performance is an estimate of
// expected accuracy and estimated_cost is an estimate (exact prompt tokens + the
// router's average response length). The LLM is never actually called.

export type ModelScore = {
  model_name: string
  display_name: string
  predicted_performance: number
  estimated_cost: number
  utility: number
  rank: number
}

export type RouterDecision = {
  router_type: string
  best_model: string
  best_model_display: string
  ranking: ModelScore[]
  note: string
}

export type RouteResponse = {
  prompt: string
  willingness_to_pay: number
  decisions: RouterDecision[]
}

export async function routeTask(
  prompt: string,
  willingnessToPay: number,
  routerTypes?: string[],
  routerSet?: string,
): Promise<RouteResponse> {
  const res = await fetch("/api/route", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      prompt,
      willingness_to_pay: willingnessToPay,
      router_types: routerTypes ?? null,
      // Empty/undefined selects the default global router set.
      router_set: routerSet || null,
    }),
  })
  if (!res.ok) {
    // The gateway maps "routers not loaded" -> 409 and "empty prompt" -> 400
    // with a human-readable detail; surface it.
    let detail = "Failed to route prompt"
    try {
      detail = (await res.json()).detail ?? detail
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail)
  }
  return res.json()
}

// ---- Router sets (/api/router-sets) ----

export type RouterSet = {
  name: string // pass as router_set to routeTask
  is_default: boolean
  router_types: string[]
  model_count: number
  created_at: string
}

export async function fetchRouterSets(): Promise<RouterSet[]> {
  const res = await fetch("/api/router-sets")
  if (!res.ok) throw new Error("Failed to fetch router sets")
  const data = await res.json()
  return data.sets
}

// ---- Tuning upload schema (/api/tuning-schema) ----

export type TuningSchema = {
  recognized_models: string[] // the only valid model column headers
  min_rows: number
  min_labels_per_model: number
  min_models: number
}

export async function fetchTuningSchema(): Promise<TuningSchema> {
  const res = await fetch("/api/tuning-schema")
  if (!res.ok) throw new Error("Failed to fetch tuning schema")
  return res.json()
}

// ---- Router tuning (/api/tune) ----

// Tuning fits a fresh router set from the user's own labeled data so routing can
// match their task distribution. The fit runs async in the background; the UI
// kicks it off, then polls getTuningStatus until it succeeds or fails.

export type RouterQuality = {
  router_type: string
  routed_accuracy: number // accuracy of the model this router picks (held-out)
  routed_cost: number // total estimated USD over the held-out split
}

export type TuningMetrics = {
  train_rows: number
  eval_rows: number
  best_single_accuracy: number // best fixed model on the held-out split
  best_single_model: string
  oracle_accuracy: number // upper bound (always pick a correct model)
  routers: RouterQuality[]
}

export type TuningStatus = {
  job_id: string
  dataset_name: string
  status: "pending" | "running" | "succeeded" | "failed" | string
  error: string
  run_id: string
  router_types: string[]
  metrics: TuningMetrics | null
}

export async function startTuning(
  file: File,
  datasetName: string,
  routerTypes: string[],
): Promise<{ job_id: string; dataset_name: string; status: string }> {
  const form = new FormData()
  form.append("file", file)
  form.append("dataset_name", datasetName)
  form.append("router_types", routerTypes.join(","))
  const res = await fetch("/api/tune", { method: "POST", body: form })
  if (!res.ok) {
    let detail = "Failed to start tuning"
    try {
      detail = (await res.json()).detail ?? detail
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail)
  }
  return res.json()
}

export async function getTuningStatus(jobId: string): Promise<TuningStatus> {
  const res = await fetch(`/api/tune/${encodeURIComponent(jobId)}`)
  if (!res.ok) throw new Error("Failed to fetch tuning status")
  return res.json()
}
