# Separate order and kitchen sites

Deploy three Vercel projects from the same checkout: two browser sites and one
shared FastAPI backend. Both screens read the same Square Sandbox location.
The order site has no kitchen navigation; the kitchen site has no order-entry
navigation. Both open directly at `/` and preserve their own old route alias.

Production URLs in the `iceberg-projects` Vercel account:

- Order: https://fullfill-order.vercel.app
- Kitchen: https://fullfill-kitchen.vercel.app
- API: https://fullfill-api.vercel.app

The ignored root `.env` stores the shared `FULLFILL_ACCESS_KEY`. The public demo
uses `fullfill` on both sites and displays it on both lock screens. Set that same value
in the API project's Vercel environment.

| Project | Root directory | Framework | Build command | Output |
| --- | --- | --- | --- | --- |
| `fullfill-api` | repository root | FastAPI | automatic Python build | automatic |
| `fullfill-order` | `apps/web` | Vite | `npm run build:order` | `dist/order` |
| `fullfill-kitchen` | `apps/web` | Vite | `npm run build:fulfill` | `dist/fulfill` |

The API entry point is `app.py`; the root Python workspace and `uv.lock` supply
its dependencies. The frontend projects use `apps/web/vercel.json` for SPA
fallbacks and headers. A separate-site build fails when its HTTPS API URL is
missing, preventing an apparently successful deployment that calls localhost.

## Environment variables

Set these only on the API project, as server-side secrets:

- `SQUARE_ENVIRONMENT=sandbox`
- `SQUARE_ACCESS_TOKEN` and `SQUARE_LOCATION_ID` from the Sandbox account
- `FULLFILL_ACCESS_KEY=fullfill`: the shared public demo access code for both sites
- `FULLFILL_WEB_ORIGINS`: the exact order and kitchen HTTPS origins, separated
  by a comma, without trailing slashes

On both frontend projects, set `VITE_API_BASE_URL` to the API's production HTTPS
origin, without a path. This URL is public. Never put Square or Perceptron
credentials in a `VITE_` variable: Vite includes those values in browser code.

Both sites ask for the same access code, sent in an Authorization header and
remembered per tab in session storage. The shared code authorizes ordering and
all kitchen operations. Hosted deployments fail closed if it is missing.
Local development without a code remains available. The retired
`FULLFILL_KITCHEN_KEY` setting is ignored; only `FULLFILL_ACCESS_KEY` is accepted.

The kitchen **Menu** tab opens directly using the shared session.
There is no additional menu editing code or secret to configure.
Run `uv run python scripts/seed_square_menu.py` once against the same Sandbox
location before deploying the catalog-backed menu. Menu edits persist in Square;
deployment does not overwrite them. See [the menu workflow](square-demo.md).

## Automatic deployments

The repository's **Checks and deploy** GitHub Actions workflow runs `make check`
on pushes and pull requests. After checks pass for a push or merge to `main`, it
deploys the API first, then the ordering site, then the kitchen site. Each project
uses its existing Vercel root directory, build command, and production environment.
Vercel performs the production builds, so Square credentials stay in Vercel and do
not need to be copied into GitHub Actions.

Production runs are serialized; a run skips deployment if its commit has already
been superseded on `main`. Pull requests and other branches only run checks.
The GitHub Actions **Run workflow** button can retry the current `main` deployment.
If any deployment fails, later projects are not deployed; earlier successful
deployments remain live. Fix the problem and run the workflow on `main` again.

GitHub repository secrets:

| Secret | Vercel project scope |
| --- | --- |
| `VERCEL_API_TOKEN` | `fullfill-api` |
| `VERCEL_ORDER_TOKEN` | `fullfill-order` |
| `VERCEL_KITCHEN_TOKEN` | `fullfill-kitchen` |

These are dedicated Vercel tokens, scoped to the corresponding project within
`iceberg-projects`. Project/team IDs are identifiers stored in the workflow, not
credentials. Update the corresponding repository secret when rotating a token.
The initial deployment tokens expire one year after creation; replace them in
GitHub before expiration to keep automatic deployments running.
The workflow uses Vercel CLI 64.5.0 and GitHub's read-only repository token.
It passes project/team IDs through `VERCEL_PROJECT_ID` and `VERCEL_ORG_ID`.
Do not add `--scope` to these CI commands: that triggers an account lookup that
project-scoped tokens cannot perform.

Repository ownership transfer and Vercel's native GitHub integration are not
required. See the [official GitHub Actions guide](https://vercel.com/kb/guide/how-can-i-use-github-actions-with-vercel).

## Manual deployment

Create the projects once using the settings above, then deploy from the repository
root with the official Vercel CLI. Select the appropriate account with `--scope`.

```sh
npx vercel login
npx vercel deploy --prod --project fullfill-api --scope iceberg-projects
npx vercel deploy --prod --project fullfill-order --scope iceberg-projects
npx vercel deploy --prod --project fullfill-kitchen --scope iceberg-projects
```

Deploy the API first, configure its returned stable URL on both frontend
projects, then deploy the frontends. Configure the two returned frontend origins
on the API and redeploy the API. Use stable production aliases, not changing
deployment URLs. `.vercelignore` excludes `.env`, dependencies, local output,
and agent configuration from CLI uploads. `.vercel/` stays out of Git.

Manual CLI deployment remains available for recovery. Normal updates should go
through `main` so they receive the automated checks and deploy all three projects.

## Local development and checks

Run `make dev-api`, `make dev-order`, and `make dev-fulfill` in separate terminals.
Open the order site at `http://127.0.0.1:5174` and kitchen at
`http://127.0.0.1:5175`. The local Vite proxies share the API on port 8000.
The original combined development view still runs with `make dev-web` on 5173;
the fake vision scenarios are only in that combined view at `/demo`.

`make check` validates Python, all tests, generated contracts, and all three
frontend builds. Its reserved `api.example.invalid` URL is only a build check;
it is never a real deployment configuration.

For a live smoke test, enter the demo code in each site, place a Sandbox order
on the order site, and verify the exact ticket ID and quantities appear on the
kitchen site. Also confirm anonymous API requests return 401. No payment or
camera call is made. Vision checks are still a separate integration.
