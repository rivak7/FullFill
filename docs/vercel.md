# Separate order and kitchen sites

Deploy three Vercel projects from the same checkout: two browser sites and one
shared FastAPI backend. Both screens read the same Square Sandbox location.
The order site has no kitchen navigation; the kitchen site has no order-entry
navigation. Both open directly at `/` and preserve their own old route alias.

Production URLs in the `iceberg-projects` Vercel account:

- Order: https://fullfill-order.vercel.app
- Kitchen: https://fullfill-kitchen.vercel.app
- API: https://fullfill-api.vercel.app

The demo access code is stored in the ignored root `.env` as
`FULLFILL_ACCESS_KEY`. Share it with the people using the demonstration; do not
share the Square access token. The API also stores this code as a Vercel secret.

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
- `FULLFILL_ACCESS_KEY`: a randomly generated access code, at least 32 characters
- `FULLFILL_WEB_ORIGINS`: the exact order and kitchen HTTPS origins, separated
  by a comma, without trailing slashes

On both frontend projects, set `VITE_API_BASE_URL` to the API's production HTTPS
origin, without a path. This URL is public. Never put an access code or Square
credential in a `VITE_` variable: Vite includes those values in browser code.

Each site asks for the demo access code once per tab session. It is sent in an
Authorization header and remembered in session storage. The API checks it on
order reads and writes. Hosted deployments fail closed if the code is missing
or too short; local development without a code remains available. Rotating the
code invalidates existing sessions. This shared demo code is not per-user access
control and is intended for the Sandbox demonstration.

## Deploy

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

Automatic deployments require the Vercel GitHub integration to have access to
`rivak7/FullFill`. If importing the repository reports that it cannot be found,
the repository owner must grant the integration access before connecting it.
CLI deployments work from the authorized checkout independently of that Git
connection. Git pushes alone do not redeploy projects without a Git connection.
The initial deployment used the CLI because the account's GitHub integration
could not see this shared repository; the Git connection is still outstanding.

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
