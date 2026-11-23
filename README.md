# Cognivio

Memory for AI coding tools.

Claude Code, Cursor and Codex forget your project every session. Each new session rereads
the same files, asks the same questions and repeats the mistake someone fixed last month.
Cognivio is where they keep what they learn. The agent reads your team's notes before it
touches a file and writes a short note when it finishes.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/how-it-works-dark.svg">
  <img src="docs/how-it-works-light.svg" alt="A coding agent asks Cognivio for context, gets the project map and the relevant docs, does the work, then writes back what it learned." width="960">
</picture>

Cognivio is a server with a web workspace. Agents talk to it over the Model Context
Protocol (MCP).

## Two ways to use it

- **Hosted.** Sign up at [cognivio.app](https://cognivio.app). It is free for one person.
  For a team, email [hello@hyperlynx.blue](mailto:hello@hyperlynx.blue).
- **Self-hosted.** Cognivio is open source. Anyone can read the code, change it and run it
  on their own server, with no limit on people, teams or projects. It runs from one Docker
  image plus MongoDB. The [quick start](#quick-start) takes about a minute.

The server is licensed under AGPL-3.0 and the local connector under MIT. See
[License](#license) for what that asks of you.

## What changes for your team

- The agent starts each task with the decisions, gotchas and layout your team already
  wrote down. One `prime_context` call returns the project map and the most relevant docs
  as excerpts, so the agent does not crawl the codebase to get oriented.
- What one agent learns, every other agent on the team gets. A lesson written from Claude
  Code on Monday is there for a teammate's Cursor session on Tuesday.
- Notes stay short. Writing to an existing title updates that doc in place, so reruns do
  not pile up duplicates.
- Your notes stay on your server. Search uses an embedding model that runs inside the
  container on CPU. The server makes no calls to any model API.
- You stay in charge of what agents write. Turn on the review queue and agent writes wait
  as drafts until a person approves them. Every doc keeps its version history.

## Quick start

You need Docker with Compose 2.24 or newer. Docker Desktop on macOS and Windows has it.

```bash
git clone https://github.com/Elbani/cognivio.git
cd cognivio
docker compose up -d
```

Open http://localhost:8080 and register. You get an organization and a team right away.

That is the whole setup, on macOS, Linux and Windows. Compose pulls the published image,
`ghcr.io/elbani/cognivio`, for amd64 and arm64, and starts MongoDB next to it. Nothing
builds on your machine. The server creates its signing secret on first start and keeps it
in a Docker volume, and your docs live in a second volume. Both survive restarts and
updates. `docker compose down -v` deletes them.

To change a setting, copy `.env.example` to `.env`, edit it and run `docker compose up -d`
again. See [Configuration](#configuration).

With no email provider configured, new accounts skip email verification, and a password
reset link is written to the server log instead of emailed. Read it with
`docker compose logs app`.

To update, run `git pull`, `docker compose pull` and then `docker compose up -d`. To run
your own changes, `docker compose up -d --build` builds the image from your checkout.

## Connect your agent

Create a key in the app under Agents, API keys. Keys start with `ak_`.

Claude Code:

```bash
claude mcp add --transport http cognivio http://localhost:8080/mcp \
  --header "Authorization: Bearer ak_..."
```

Cursor and Codex take the same URL and header in their MCP config. The Help & API page in
the app generates the exact config for all three.

Then tell the agent: "seed our Cognivio knowledge base". It calls `seed_plan`, scans your
repo and writes the first set of docs itself. You fix what it got wrong.

To make the agent use Cognivio on every task, ask it to call `setup_rule`. The tool returns
the rule file for Claude Code, Cursor or Codex, and the agent writes it into your repo.

There is also a local stdio connector for tools that cannot reach a remote MCP endpoint.
See [`mcp_server/README.md`](mcp_server/README.md).

## How it works

A doc is a Markdown document with a type: `map`, `architecture`, `decision`, `playbook`,
`incident`, `lesson` or `note`. Docs link to each other with `[[wiki links]]`. Each team
has one Project Map, which is the page an agent reads first.

1. Before a task, the agent calls `prime_context("the task")`. It gets the Project Map and
   the best-matching docs as excerpts. Ranking combines keyword matching with embedding
   similarity, so a task phrased differently from the doc still finds it.
2. The agent calls `get_memory` for the one or two docs it needs in full and follows the
   file pointers and links inside them.
3. It does the work.
4. It calls `write_memory` with anything non-obvious it found. It can also call
   `mark_helpful` on a doc, which moves that doc up or down in later results.

## Features

- Typed, linked docs with a Project Map and a link graph you can browse.
- Search by meaning and by keyword. The embedding model is `BAAI/bge-small-en-v1.5`,
  run with `fastembed` on ONNX. Set `EMBEDDINGS_ENABLED=false` for keyword search only.
- A review queue that holds agent writes as drafts until someone approves them.
- Version history on every doc, a Verify button, and a stale flag after 90 days without
  verification.
- Insights: which docs agents read, which searches found nothing, and which docs agents
  rated unhelpful. The failed searches are your list of docs to write next.
- Repo coverage and drift. Connect a read-only GitHub or GitLab token and Cognivio shows
  the parts of the repo no doc mentions and the docs whose cited files have changed.
- Project documentation. The agent writes a developer handbook (overview, architecture,
  setup) and the server stores each run as a snapshot you can diff. Agents never retrieve
  these, so they do not crowd the knowledge base.
- Organizations, teams, roles and scoped API keys.
- Single sign-on with OpenID Connect (Google Workspace, Okta, Entra ID, Keycloak and
  others), with an option to turn off password login for your email domains.
- An admin console for users, organizations, security events and key revocation.

## What is in this repo

- `backend/` is a FastAPI app on MongoDB. It serves the agent API (`/api/v1`), the web
  app's API (`/api`), the remote MCP endpoint (`/mcp`) and the built frontend. It starts at
  `backend/app/main.py`.
- `frontend/` is the React and Vite workspace. It starts at `frontend/src/App.tsx`.
- `mcp_server/` is the local stdio MCP connector, a thin client over `/api/v1`.

## Local development

Backend, with Python 3.12 and a MongoDB on `localhost:27017`:

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
JWT_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))") \
  MONGO_URI=mongodb://localhost:27017 uvicorn app.main:app --reload
pytest            # uses a separate test database and drops it
```

Frontend, with Node 22:

```bash
cd frontend
npm ci
npm run dev       # http://localhost:5173, proxies /api to the backend
npm run build     # type-check and production bundle in frontend/dist
```

## Configuration

Set these in the environment or in `.env`. See `.env.example`.

| Variable | Purpose |
|---|---|
| `JWT_SECRET` | Signs sessions and encrypts stored repo tokens. At least 32 random characters. The API refuses to start without it, unless `JWT_SECRET_FILE` is set. |
| `JWT_SECRET_FILE` | A file path. When `JWT_SECRET` is empty, the server reads the secret from this file and creates it on first start. The compose file sets it to a path in a volume. |
| `MONGO_URI`, `MONGO_DB` | MongoDB connection and database name. |
| `PUBLIC_URL` | The app's public URL. Email links are built from it, and the session cookie is marked Secure when it is https. |
| `ADMIN_EMAILS` | Comma-separated emails that can open the `/admin` console. |
| `REGISTRATION_OPEN` | `false` closes sign-up. Default `true`. |
| `RESEND_API_KEY`, `EMAIL_FROM` | Email through Resend. With no key, the server sends no email and new accounts skip verification. With a key, `EMAIL_FROM` and `PUBLIC_URL` are required. |
| `SELF_HOSTED` | Default `true`, which means no plan limits. `false` turns on the free plan (one person) and the Teams plan, for running a hosted service. |
| `FORWARDED_ALLOW_IPS` | Addresses of the reverse proxies uvicorn trusts for the client IP. |
| `EMBEDDINGS_ENABLED` | `false` turns off the embedding model and leaves keyword search. |
| `CORS_ORIGINS` | Comma-separated allowed origins. The web app is same-origin in production. |
| `SSO_SESSION_HOURS` | How long a single sign-on session lasts before the person signs in through the identity provider again. Default `12`. |
| `CONTACT_EMAIL` | Contact address for the Teams plan when `SELF_HOSTED=false`. Shown in plan limit messages. |
| `DISABLE_DOCS` | `true` hides `/docs`, `/redoc` and `/openapi.json`. |

## Deployment

One image holds the frontend, the connector and the backend, so any host that runs a
container and reaches a MongoDB works. MongoDB is not in the image. Use the published
image or build your own from the `Dockerfile`.

| Tag | What it is |
|---|---|
| `ghcr.io/elbani/cognivio:latest` | The newest release. |
| `ghcr.io/elbani/cognivio:0.1.1` | One release. Pin this in production. |
| `ghcr.io/elbani/cognivio:main` | The current `main` branch. |

### Settings are environment variables

The image has no config file inside it. Every setting in the
[Configuration](#configuration) table is an environment variable that you pass to the
container.

To run it on your own laptop, use the [quick start](#quick-start). It needs no settings
at all. This section is for running it on a server.

- With Docker Compose, put them in `.env`. The compose file passes that file to the
  container. Run `docker compose up -d` again after you change it.
- With plain Docker, pass the same file with `--env-file`, or single values with `-e`:

  ```bash
  docker run -d --name cognivio -p 8080:8000 --env-file .env \
    -e MONGO_URI="mongodb://your-mongo-host:27017" \
    ghcr.io/elbani/cognivio:0.1.1
  ```

- On a hosting platform or Kubernetes, point it at the image and enter the variables in
  its settings or secrets store.

Outside the compose file, `MONGO_URI` and `JWT_SECRET` are required. Generate the secret
with `openssl rand -hex 32` and keep it the same across restarts. A new value signs
everyone out and makes the stored repo tokens and single sign-on client secrets
unreadable. If you would rather have the server create it, mount a volume and set
`JWT_SECRET_FILE` to a path inside it, as `docker-compose.yml` does. Back that file up
with the database.

### Checklist

- Set `JWT_SECRET` and `MONGO_URI` as secrets on the host.
- Set `PUBLIC_URL` and `CORS_ORIGINS` to the app's public URL, and `DISABLE_DOCS=true`.
- The container listens on `$PORT`, or 8000 when the host sets none.
- Point the host's health check at `/api/health`.
- Serve it over HTTPS. Agents send their API key in a header on every request.
- Set `FORWARDED_ALLOW_IPS` to your proxy's address. Rate limits are per client IP, and
  without it every request appears to come from the proxy and shares one limit.

Before the server is reachable from the internet:

- Register the accounts listed in `ADMIN_EMAILS` yourself. With email off, nobody has to
  prove they own an address, so whoever registers an admin address first gets the console.
- Set `REGISTRATION_OPEN=false` once your team has accounts. Otherwise anyone who finds the
  URL can sign up. They cannot see your organization's docs, but they can create their own.
- Or configure Resend, which makes every new account verify its email address.

## Single sign-on

Cognivio signs people in through any OpenID Connect provider. A platform admin (an
account in `ADMIN_EMAILS`) sets it up per organization, in the admin console under
Organizations, then the organization's detail view.

1. Create an OIDC web application at your identity provider. Use the redirect URL the
   form shows, which is `PUBLIC_URL` plus `/api/auth/sso/callback`.
2. Enter the issuer URL, client ID, client secret and the email domains the organization
   owns. Saving checks that the issuer's OpenID configuration is reachable.
3. People with an address in those domains choose "Sign in with SSO" on the login page.
   A first sign-in creates their account and adds them to the organization with the
   role you picked.

What to know before turning it on:

- The identity provider can sign in as any address in the domains you enter, so only
  enter domains the organization owns. This is why organization admins cannot change
  these settings themselves. One domain belongs to one organization.
- "Require" turns off password login and registration for those domains. Platform
  admins keep password login, so a broken provider cannot lock you out.
- The first time an existing account signs in through the provider, its old password
  and sessions stop working. The person can set a new password by email reset.
- The provider must send an `email` claim in the ID token. The issuer must use https.
- A single sign-on session ends after `SSO_SESSION_HOURS`. Someone you deactivate at
  the provider loses the web app within that time.
- Removing a member from an organization revokes the API keys they created there.
  Deactivating someone at the provider does not: there is no SCIM yet, so remove the
  member in Cognivio too, or their keys keep working.

## Questions and contact

Cognivio is built by [HyperLynx](https://hyperlynx.blue).

- Ask a question or tell us how you use Cognivio in
  [Discussions](https://github.com/Elbani/cognivio/discussions).
- Report a bug or ask for a feature in
  [Issues](https://github.com/Elbani/cognivio/issues).
- Email [hello@hyperlynx.blue](mailto:hello@hyperlynx.blue) for anything else, such as
  the Teams plan or working with us.
- Reach the maintainer, Elban, on X at [@axhiElban](https://x.com/axhiElban).
- Report a vulnerability privately, as [`SECURITY.md`](SECURITY.md) describes.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Report vulnerabilities privately as described in
[`SECURITY.md`](SECURITY.md).

## License

- Everything except `mcp_server/` is licensed under the GNU Affero General Public License
  v3.0. See [`LICENSE`](LICENSE). If you run a modified version as a network service, the
  AGPL requires you to offer your users the modified source.
- `mcp_server/`, the local stdio connector, is licensed under MIT. See
  [`mcp_server/LICENSE`](mcp_server/LICENSE).

The licenses above do not cover the Cognivio name and logo. A fork needs its own name
and logo.
