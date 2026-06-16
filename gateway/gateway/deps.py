"""FastAPI dependencies.

Shared pre-request logic used by multiple routes lives here; routes inject it via
Depends(...) to avoid repeating the same checks in every endpoint.
"""
from fastapi import HTTPException

from gateway.grpc_client import client


def get_stub():
    """Return the gRPC stub to the routerbench service, or 503 if not connected.

    Routes use this to talk to the microservice without each one re-checking
    that the client is ready.
    """
    if client.stub is None:
        raise HTTPException(status_code=503, detail="gRPC client not connected")
    return client.stub
