"""Route aggregation layer.

Combines the routers from each module under routes/ into a single api_router,
mounted once by main.py. To add a new endpoint: create a file under routes/,
then add one include_router line here.
"""
from fastapi import APIRouter

from gateway.routes import chart, evals, results

api_router = APIRouter()
api_router.include_router(results.router)  # /api/results
api_router.include_router(evals.router)    # /api/evals
api_router.include_router(chart.router)    # /api/chart
