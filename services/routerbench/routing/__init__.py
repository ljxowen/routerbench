"""Predict side: runtime single-prompt routing.

Turns fitted routers + a user prompt into ranked model recommendations for the
``RouteTask`` RPC. Read-only at serve time; the training/tuning counterpart lives
in the ``tuning`` package. The two only meet at ``routers.router_store`` (one
writes fitted routers, the other reads them).
"""
