"""Isolated NLI Verifier Worker Package (PROD-VERIFIER-02B).

This package owns the neural claim-verification execution boundary.

Architecture invariant:
    Main Python 3.14 runtime process must NEVER import or execute
    torch/transformers. All neural inference lives behind this worker
    boundary, reached via a parent-owned stdin/stdout JSON-lines IPC
    protocol (no network listener, no pickle, no arbitrary object
    serialization).

Modules:
    protocol       - protocol version + frame validation constants (torch-free)
    main           - worker entry point (owns torch/transformers/model)
    neural_backend - worker-only inference implementation (torch/transformers)
    client         - main-process facade implementing BaseClaimVerifier

The main-process client and the shared contracts in runtime.claim_verification
are torch-free by design; only `main`/`neural_backend` may touch ML imports,
and they are executed exclusively inside the worker interpreter.
"""
