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
