# FullFill

DubHacks '26 order checker. [order-checker.md](order-checker.md) is the main project plan.

**Current status:** Square Sandbox order entry and the live fulfillment queue work
at `/order` and `/fulfill`. See [the Square demo setup](docs/square-demo.md).
The vision adapter and comparison logic exist, but camera/check orchestration,
persistence, and result delivery still need integration. Existing `config.py`
and `camera_input_number.py` are preserved.

| Folder | Work area |
| --- | --- |
| `apps/web/` | React/TypeScript UI — William |
| `apps/capture/` | Python camera pipeline — William |
| `apps/api/` | FastAPI, workflow, Perceptron and storage adapters — Roy |
| `apps/photon_bridge/` | Optional messaging integration — Roy |
| `packages/contracts/` | Shared Python models and generated TypeScript — agree together |
| `eval/`, `fixtures/`, `tests/` | Evaluation and shared cases — Rishabh/everyone |

Use **Python 3.13**, uv, and Node.js 22.12+.

```sh
make setup
make dev-api  # Order API, reads Square credentials from the root .env
make dev-web  # /order and /fulfill, in another terminal
```

Run `make contracts` after editing shared models and `make check` before pushing.
No camera credentials are needed for order entry. Square Sandbox credentials are
required to create or retrieve orders; configuration errors are shown in the UI.

See [the team development guide](docs/team-development.md) for boundaries, commands,
and remaining work, and [the system design](docs/system-design.md) for the target architecture.
