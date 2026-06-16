"""FastAPI gateway entry point.

The gateway exposes REST/HTTP to the frontend and forwards everything to the
routerbench gRPC microservice. It loads no data itself — it only wires up
lifespan (gRPC connection), CORS, and the routes. Run from the gateway/ dir:
    uvicorn gateway.main:app --reload --port 8000
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from gateway.config import CORS_METHODS, CORS_ORIGINS
from gateway.grpc_client import client
from gateway.router import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Open the gRPC channel to the microservice on startup, reused by all
    # requests; close it cleanly on shutdown.
    client.connect()
    yield
    client.close()


app = FastAPI(lifespan=lifespan)

# Allow the frontend (on a different port, e.g. localhost:3000) to call this API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=CORS_METHODS,
    allow_headers=["*"],
)

# Mount the aggregated router; all /api/* endpoints take effect from here.
app.include_router(api_router)
