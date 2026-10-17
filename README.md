# FullFill

DubHacks '26 order checker. [order-checker.md](order-checker.md) is the main project plan.

**Current status: scaffold only.** App entry points, shared contracts, interfaces, and
placeholder modules are present. The team still needs to implement the product behavior.
Existing `config.py` and `camera_input_number.py` are preserved.

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
make dev-api  # API entry point, in one terminal
make dev-web  # Frontend placeholder, in another terminal
```

Run `make contracts` after editing shared models and `make check` before pushing.
No camera or API credentials are needed to start the scaffold.

See [the team development guide](docs/team-development.md) for boundaries, commands,
and remaining work, and [the system design](docs/system-design.md) for the target architecture.
