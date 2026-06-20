"""gRPC client to the routerbench microservice.

The gateway holds no data of its own; it forwards each request to the
routerbench gRPC service over this client. A single channel/stub is created at
startup and reused for every request (channels are designed to be long-lived).

The stubs are generated from the shared proto/ into gateway/_proto — the gateway
keeps its own copy so it stays independent of the service's codebase.
"""
import grpc

from gateway.config import GRPC_TARGET
from gateway.observability import ClientMetricsInterceptor
from gateway._proto.routerbench.v1 import routerbench_pb2_grpc as pb_grpc


class GrpcClient:
    def __init__(self) -> None:
        self._channel = None
        self.stub = None

    def connect(self) -> None:
        # insecure_channel is lazy: it doesn't block waiting for the service,
        # the actual connection happens on the first RPC call.
        channel = grpc.insecure_channel(GRPC_TARGET)
        # Wrap the channel so every RPC made through the stub is measured for
        # Prometheus (started/handled counts + latency histogram).
        self._channel = grpc.intercept_channel(channel, ClientMetricsInterceptor())
        self.stub = pb_grpc.RouterBenchStub(self._channel)

    def close(self) -> None:
        if self._channel is not None:
            self._channel.close()
            self._channel = None
            self.stub = None


# Single instance, connected by main.py's lifespan at startup.
client = GrpcClient()
