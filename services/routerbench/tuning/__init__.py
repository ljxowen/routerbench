"""Train side: fit a router set from caller-supplied data (async tuning jobs).

The counterpart to the read-only ``routing`` package. Validation, fitting, the
held-out quality report, and the background job machinery live here. The two
packages never import each other; they meet only at ``routers.router_store``
(this side writes fitted routers, ``routing`` reads them).
"""
