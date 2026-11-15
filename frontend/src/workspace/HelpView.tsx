import { useEffect, useState } from "react";
import { apiRequest } from "../lib/api";
import { ruleFileFor } from "./cognivioRule";

const BASE = typeof window !== "undefined" ? window.location.origin : "https://your-host";
// Cross-platform uv installer (macOS/Linux). Windows: see https://docs.astral.sh/uv/
const UV_INSTALL = "curl -LsSf https://astral.sh/uv/install.sh | sh";

export function HelpView() {
  const [connectorUrl, setConnectorUrl] = useState<string | null>(null);
  useEffect(() => {
    apiRequest<{ available: boolean; path?: string }>("/api/connector")
      .then((c) => setConnectorUrl(c.available && c.path ? `${BASE}${c.path}` : null))
      .catch(() => setConnectorUrl(null));
  }, []);
  const wheel = connectorUrl ?? "<connector-url shown in Agents → Connect a tool>";
  const pipxInstall = `pipx install ${wheel}`;
  return (
    <div className="help">
      <p className="lead">
        Cognivio is a knowledge base your AI agents read before they act, and write back to as they
        learn. This guide covers the platform, the REST API, and the MCP server.
      </p>

      <div className="toc">
        <a href="#concepts">Concepts</a>
        <a href="#workspace">Using the workspace</a>
        <a href="#types">Doc types</a>
        <a href="#roles">Roles</a>
        <a href="#keys">API keys</a>
        <a href="#sso">Single sign-on</a>
        <a href="#rest">REST API</a>
        <a href="#mcp">Coding tools (MCP)</a>
        <a href="#auto">Auto-use it</a>
        <a href="#workflow">Agent workflow</a>
        <a href="#coverage">Make your KB help</a>
        <a href="#repo">Repo coverage &amp; drift</a>
      </div>

      <h2 id="concepts">Concepts</h2>
      <p>Everything is organized in a simple hierarchy:</p>
      <ul>
        <li><b>Organization</b>: your top-level workspace. Created automatically when you sign up.</li>
        <li><b>Team</b>: a space within an org with its own docs, map, and agents. You start with a <b>Main</b> team.</li>
        <li><b>Project</b>: an optional folder to group docs inside a team. Docs don't need one.</li>
        <li><b>Doc</b>: a typed Markdown document (the unit of knowledge).</li>
      </ul>
      <p>
        Docs connect to each other with <code>[[wiki links]]</code>, forming a graph. Each team has a special
        <b> Project Map</b> doc that acts as the entry point, the first thing an agent reads to orient itself.
      </p>

      <h2 id="workspace">Using the workspace</h2>
      <ul>
        <li><b>Overview</b>: health of your knowledge base: counts, what needs re-verifying, graph issues, and recent agent activity.</li>
        <li><b>Project Map</b>: read or edit your team's entry-point doc.</li>
        <li><b>Docs</b>: browse, filter, and write docs. Type <code>[[</code> in the editor to link to another doc.</li>
        <li><b>Graph</b>: see how docs connect; spot orphans and broken links.</li>
        <li><b>Agents</b>: create API keys and watch what your agents read and write.</li>
        <li><b>Insights</b>: org-wide coverage, knowledge gaps (searches that found nothing), retrieval hit-rate, agent activity, per-doc usage (most-read vs. never-read), and usefulness (docs agents rated helpful or flagged as noise).</li>
        <li><b>Repo</b>: connect this team's Git repo (read-only) to see which parts of the codebase have no docs, and which docs have drifted from the code.</li>
        <li><b>Review</b>: appears when write-back review is on: approve or dismiss the drafts agents wrote before they go live.</li>
        <li><b>Members</b>: invite people and set their roles.</li>
      </ul>
      <p>
        Every doc keeps a <b>version history</b>, open a doc and click <b>History</b> to see each revision (yours or an
        agent's), diff it against the current version, and restore it. Agent write-backs are snapshotted too, so changes
        are always reversible.
      </p>
      <p>
        Use <b>Verify</b> on a doc to mark it freshly reviewed; docs not verified in 90 days are flagged as stale.
        Switch between light and dark from the bottom of the sidebar, and re-run the guided tour anytime with
        <b> Take the tour</b>.
      </p>
      <p>
        <b>Agent write-back review (optional).</b> Turn on <b>Settings → Knowledge base → Hold for review</b> to make
        docs an agent creates or updates land as <b>drafts</b>, hidden from agent retrieval until you approve them in
        the <b>Review</b> tab. Agents can also rate a doc with <code>mark_helpful</code>: helpful docs rank higher in
        <code> prime_context</code>, and ones flagged as noise sink and surface in <b>Insights → Usefulness</b>.
      </p>

      <h2 id="types">Doc types</h2>
      <p>Pick a type when you create a doc. The API uses the value in the last column.</p>
      <table>
        <thead><tr><th>Type</th><th>Use it for</th><th>API value</th></tr></thead>
        <tbody>
          <tr><td>Project Map</td><td>Entry point that orients a reader</td><td><code>map</code></td></tr>
          <tr><td>How It Works</td><td>How a system is built, and why</td><td><code>architecture</code></td></tr>
          <tr><td>Guide</td><td>A step-by-step procedure</td><td><code>playbook</code></td></tr>
          <tr><td>Incident</td><td>What broke, root cause, and the fix</td><td><code>incident</code></td></tr>
          <tr><td>Decision</td><td>A choice, its context, and trade-offs</td><td><code>decision</code></td></tr>
          <tr><td>Lesson</td><td>A durable takeaway worth keeping</td><td><code>lesson</code></td></tr>
          <tr><td>Note</td><td>Anything else</td><td><code>note</code></td></tr>
        </tbody>
      </table>

      <h2 id="roles">Roles</h2>
      <ul>
        <li><b>Owner</b> / <b>Admin</b>, full access, plus manage members and API keys.</li>
        <li><b>Editor</b>: create and edit docs.</li>
        <li><b>Viewer</b>: read-only.</li>
      </ul>

      <h2 id="keys">API keys</h2>
      <p>
        Agents authenticate with an API key (admins create these under <b>Agents → API keys</b>). A key belongs to an
        org, can be restricted to a single team, and carries scopes:
      </p>
      <ul>
        <li><code>memory:read</code>: read and search docs.</li>
        <li><code>map:read</code>: read the Project Map + graph.</li>
        <li><code>memory:write</code>: create docs (write-back).</li>
      </ul>
      <p>The full key (<code>ak_…</code>) is shown once at creation. Pass it as a Bearer token:</p>
      <pre><code>{`Authorization: Bearer ak_your_key_here`}</code></pre>
      <p>Revoking a key takes effect immediately. Every agent call is recorded in the audit log (Agents → Activity).</p>
      <p>Removing a member from the organization revokes the API keys that member created.</p>

      <h2 id="sso">Single sign-on</h2>
      <p>
        Your team can sign in through your company's identity provider instead of a password. Cognivio speaks
        OpenID Connect, which Google Workspace, Okta, Microsoft Entra ID and Keycloak all support.
      </p>
      <h3>Who sets it up</h3>
      <p>
        A platform admin, meaning an account listed in the server's <code>ADMIN_EMAILS</code> setting. Organization
        owners and admins cannot change it. The identity provider can sign in as any address in the email domains
        you enter, so the person who runs the server confirms the organization owns them.
      </p>
      <h3>Steps</h3>
      <ol>
        <li>Open the admin console at <code>/admin</code>, go to <b>Organizations</b>, open the organization, and
          scroll to <b>Single sign-on</b>.</li>
        <li>Copy the redirect URL the form shows. On this server it is <code>{`${BASE}/api/auth/sso/callback`}</code>,
          unless the server's <code>PUBLIC_URL</code> says otherwise.</li>
        <li>At your identity provider, create an OpenID Connect <b>web application</b> and paste that redirect URL
          into it. The provider gives you a client ID and a client secret.</li>
        <li>Back in the form, enter the issuer URL (see the table below), the client ID, the client secret and your
          email domains, for example <code>example.com</code>. Pick the role new members get.</li>
        <li>Save. Cognivio checks that it can read the provider's configuration and reports an error if the issuer
          URL is wrong.</li>
        <li>Test it: sign out, type your work email on the login page and choose <b>Sign in with SSO</b>.</li>
      </ol>
      <h3>Issuer URL by provider</h3>
      <table>
        <thead><tr><th>Provider</th><th>Issuer URL</th><th>Notes</th></tr></thead>
        <tbody>
          <tr><td>Google Workspace</td><td><code>https://accounts.google.com</code></td>
            <td>Create an OAuth client of type Web application in the Google Cloud console.</td></tr>
          <tr><td>Okta</td><td><code>https://your-company.okta.com</code></td>
            <td>Create an OIDC Web Application and assign the people who should have access.</td></tr>
          <tr><td>Microsoft Entra ID</td><td><code>https://login.microsoftonline.com/TENANT_ID/v2.0</code></td>
            <td>Under Token configuration, add the optional claim <code>email</code> to the ID token. Without it
              sign-in fails, because Entra does not send the address by default.</td></tr>
          <tr><td>Keycloak</td><td><code>https://your-host/realms/REALM</code></td>
            <td>Create a client with Client authentication on and the Standard flow enabled.</td></tr>
        </tbody>
      </table>
      <p>The issuer must use https, and the provider must send the person's email address in the ID token.</p>
      <h3>What changes for your team</h3>
      <ul>
        <li>Anyone with an address in your domains can sign in. A first sign-in creates their account and adds them
          to the organization with the role you picked.</li>
        <li><b>Require it</b> turns off password login and sign-up for your domains. Platform admins keep password
          login, so a provider outage cannot lock the server's operator out.</li>
        <li>The first time an existing account signs in through the provider, its old password and sessions stop
          working. The person can set a new password with <b>Forgot password</b> if they still need one.</li>
        <li>A single sign-on session lasts 12 hours by default (<code>SSO_SESSION_HOURS</code>). After that the
          person signs in through the provider again, so someone you deactivate there loses access to the
          workspace within that time.</li>
        <li>Deactivating someone at the provider does not revoke the API keys they created. Remove them under
          <b>Members</b> as well, which does.</li>
      </ul>
      <h3>If sign-in fails</h3>
      <ul>
        <li><b>"Single sign-on is not set up for this email domain"</b>: the domain is not in the form, or
          single sign-on is turned off.</li>
        <li><b>"Your identity provider could not complete the sign-in"</b>: usually a wrong client secret, or a
          redirect URL at the provider that does not match the one in the form exactly.</li>
        <li><b>"Your identity provider did not share an email address"</b>: add the <code>email</code> claim (see
          Entra ID above).</li>
        <li><b>"That email address is outside the domains your organization signs in with"</b>: add the person's
          domain to the form.</li>
      </ul>
      <p>The reason for each failed sign-in is also recorded in the admin console under <b>Security</b>.</p>

      <h2 id="rest">REST API</h2>
      <p>All agent endpoints live under <code>/api/v1</code> and require an API key.</p>
      <table>
        <thead><tr><th>Method &amp; path</th><th>Scope</th><th>Description</th></tr></thead>
        <tbody>
          <tr><td><code>GET /api/v1/whoami</code></td><td>any</td><td>Identify the key's org, scopes, team restriction</td></tr>
          <tr><td><code>GET /api/v1/teams</code></td><td>read</td><td>Teams this key can access</td></tr>
          <tr><td><code>GET /api/v1/teams/{`{team}`}/map</code></td><td>map / read</td><td>Project Map doc + node/edge graph</td></tr>
          <tr><td><code>GET /api/v1/teams/{`{team}`}/memories</code></td><td>read</td><td>Search/list docs (no body)</td></tr>
          <tr><td><code>GET /api/v1/memories/{`{id}`}</code></td><td>read</td><td>One doc, full content</td></tr>
          <tr><td><code>GET /api/v1/memories/{`{id}`}/related</code></td><td>read</td><td>Linked + backlinked docs</td></tr>
          <tr><td><code>GET /api/v1/teams/{`{team}`}/seed-plan</code></td><td>read</td><td>Plan to initialize/fill the KB: existing docs, undocumented areas, ordered steps</td></tr>
          <tr><td><code>POST /api/v1/teams/{`{team}`}/memories</code></td><td>write</td><td>Create a doc (upserts by title)</td></tr>
          <tr><td><code>POST /api/v1/memories/{`{id}`}/feedback</code></td><td>read</td><td>Rate whether a doc helped (<code>{`{"helpful": true|false}`}</code>)</td></tr>
        </tbody>
      </table>
      <p>
        Search supports <code>q</code> (text), <code>type</code> (API value above), <code>tag</code>,
        <code>status</code>, and <code>limit</code>.
      </p>
      <pre><code>{`# Who am I?
curl -H "Authorization: Bearer ak_…" ${BASE}/api/v1/whoami

# List teams, then read a team's Project Map
curl -H "Authorization: Bearer ak_…" ${BASE}/api/v1/teams
curl -H "Authorization: Bearer ak_…" "${BASE}/api/v1/teams/TEAM_ID/map"

# Search guides about deploys, then read one
curl -H "Authorization: Bearer ak_…" \\
  "${BASE}/api/v1/teams/TEAM_ID/memories?q=deploy&type=playbook&limit=10"
curl -H "Authorization: Bearer ak_…" ${BASE}/api/v1/memories/DOC_ID

# Write back a lesson (needs memory:write)
curl -X POST -H "Authorization: Bearer ak_…" -H "Content-Type: application/json" \\
  -d '{"title":"Lesson: retry on 429","type":"lesson","content":"Use backoff. See [[Ingestion Pipeline]]."}' \\
  ${BASE}/api/v1/teams/TEAM_ID/memories`}</code></pre>

      <h2 id="mcp">Connect a coding tool (MCP)</h2>
      <p>
        Cognivio speaks the Model Context Protocol, so coding agents can use your knowledge base as native
        tools. There are two ways to connect: <b>Remote</b> (this platform hosts the MCP server, nothing to install)
        or <b>Local</b> (a small connector runs on your machine). Both use an <code>ak_</code> key from
        <b>Agents → API keys</b>.
      </p>

      <h3>Remote: zero setup (recommended)</h3>
      <p>
        The platform hosts an MCP server over Streamable HTTP at <code>{BASE}/mcp</code>. Point your tool at that URL
        with the key in an <code>Authorization</code> header, no <code>uv</code>, no <code>pipx</code>, no PATH, nothing
        to install. (Remote MCP support varies by client/version; the Local option below is the universal fallback.)
      </p>
      <pre><code>{`# Claude Code
claude mcp add --transport http cognivio ${BASE}/mcp \\
  --header "Authorization: Bearer ak_your_key_here"`}</code></pre>
      <pre><code>{`// Cursor: .cursor/mcp.json
{
  "mcpServers": {
    "cognivio": {
      "url": "${BASE}/mcp",
      "headers": { "Authorization": "Bearer ak_your_key_here" }
    }
  }
}`}</code></pre>
      <pre><code>{`# Codex: ~/.codex/config.toml
[mcp_servers.cognivio]
url = "${BASE}/mcp"
http_headers = { Authorization = "Bearer ak_your_key_here" }`}</code></pre>

      <h3>Local: stdio connector</h3>
      <h4>One-time: install a runner</h4>
      <p>
        The connector is a small Python program (3.10+) served by this platform, you don't need the repo. The simplest
        path is <a href="https://docs.astral.sh/uv/" target="_blank" rel="noreferrer">uv</a>: install it once and the
        configs below <b>fetch and run the connector on demand</b> via <code>uvx</code>, so there's no separate connector
        install to forget (the most common setup mistake):
      </p>
      <pre><code>{UV_INSTALL}</code></pre>
      <p>
        ⚠ <b>Then restart your terminal</b> (or <code>source $HOME/.local/bin/env</code>) so <code>uvx</code> lands on
        your PATH, and launch your coding tool from that shell. Check with <code>which uvx</code>, if it prints nothing,
        your tool can't start the server and you'll see <i>"Failed to connect."</i> (Adding the server only records the
        launch command; it doesn't install or verify anything.)
      </p>
      <p>
        <b>Prefer pipx?</b> Install the connector once instead, <code>{pipxInstall}</code>, then use
        <code> cognivio-mcp</code> (no <code>uvx --from …</code> wrapper) as the <code>command</code> in any snippet
        below. Either way, set <code>KB_BASE_URL</code> to this server (<code>{BASE}</code>).
      </p>

      <h3>Claude Code</h3>
      <p>Add it from the CLI:</p>
      <pre><code>{`claude mcp add cognivio \\
  --env KB_BASE_URL=${BASE} \\
  --env KB_API_KEY=ak_your_key_here \\
  -- uvx --from ${wheel} cognivio-mcp`}</code></pre>
      <p>…or commit a project <code>.mcp.json</code>:</p>
      <pre><code>{`{
  "mcpServers": {
    "cognivio": {
      "command": "uvx",
      "args": ["--from", "${wheel}", "cognivio-mcp"],
      "env": {
        "KB_BASE_URL": "${BASE}",
        "KB_API_KEY": "ak_your_key_here"
      }
    }
  }
}`}</code></pre>

      <h3>Cursor</h3>
      <p>Create <code>.cursor/mcp.json</code> in your project (or add it under <b>Settings → MCP → Add new server</b>):</p>
      <pre><code>{`{
  "mcpServers": {
    "cognivio": {
      "command": "uvx",
      "args": ["--from", "${wheel}", "cognivio-mcp"],
      "env": {
        "KB_BASE_URL": "${BASE}",
        "KB_API_KEY": "ak_your_key_here"
      }
    }
  }
}`}</code></pre>

      <h3>Codex</h3>
      <p>Add a server block to <code>~/.codex/config.toml</code>:</p>
      <pre><code>{`[mcp_servers.cognivio]
command = "uvx"
args = ["--from", "${wheel}", "cognivio-mcp"]
env = { KB_BASE_URL = "${BASE}", KB_API_KEY = "ak_your_key_here" }`}</code></pre>

      <p>Once connected, the agent gets these tools:</p>
      <table>
        <thead><tr><th>Tool</th><th>What it does</th></tr></thead>
        <tbody>
          <tr><td><code>prime_context(query, limit?)</code></td><td><b>Start here</b>: index + the most relevant docs as excerpts in one call</td></tr>
          <tr><td><code>seed_plan(team_id)</code></td><td>Call first when seeding: existing docs, undocumented areas, review state, and the ordered steps to write a starter set</td></tr>
          <tr><td><code>whoami()</code></td><td>Which org/scopes the key has</td></tr>
          <tr><td><code>list_teams()</code></td><td>Teams the key can read</td></tr>
          <tr><td><code>read_map(team_id)</code></td><td>Project Map + graph (follow-up orientation)</td></tr>
          <tr><td><code>search_memory(team_id, query, type?, tag?, limit?)</code></td><td>Find docs</td></tr>
          <tr><td><code>knowledge_gaps(days?, limit?)</code></td><td>Queries that found nothing: docs worth writing</td></tr>
          <tr><td><code>check_drift(team_id)</code></td><td>Docs whose referenced code changed after they were verified (remote: server-side repo; stdio: your working tree)</td></tr>
          <tr><td><code>plan_project_docs(team_id)</code></td><td>Call first to generate the human-facing developer handbook: recommended outline, existing sections, least-documented areas</td></tr>
          <tr><td><code>write_project_docs(team_id, summary, sections)</code></td><td>Publish the developer handbook as a new version snapshot (separate from the KB; never used in retrieval)</td></tr>
          <tr><td><code>get_memory(memory_id)</code></td><td>Read one doc in full</td></tr>
          <tr><td><code>get_related(memory_id)</code></td><td>Neighbors (links + backlinks)</td></tr>
          <tr><td><code>write_memory(team_id, title, content, type?, tags?)</code></td><td>Write back a doc (same title updates in place)</td></tr>
          <tr><td><code>mark_helpful(memory_id, helpful?, note?)</code></td><td>Rate whether a doc helped, boosts or demotes it in future <code>prime_context</code></td></tr>
          <tr><td><code>setup_rule(tool?)</code></td><td>Returns the always-on rule file for Claude Code, Cursor or Codex, for the agent to write into the repo</td></tr>
          <tr><td><code>delete_memory(memory_id)</code></td><td>Trash a duplicate/obsolete doc (restorable in the UI)</td></tr>
        </tbody>
      </table>

      <h2 id="auto">Make your agent use it automatically</h2>
      <p>
        Connecting the MCP server gives the agent the <em>tools</em>; a small always-on rule file tells it
        <em> when</em> to use them. With the rule in place your agent consults the knowledge base on every task,
        reads the map first, searches before coding, and writes findings back.
      </p>
      <p>
        <b>Easiest:</b> let the agent install it. Ask your agent to <em>"set up Cognivio for this repo"</em>, it
        calls the <code>setup_rule</code> tool and writes the correct file for your editor (the right path and, for
        Cursor, the <code>alwaysApply: true</code> frontmatter that makes it load every turn). The exact files it
        writes are below if you'd rather add them by hand.
      </p>

      <h3>Claude Code</h3>
      <p>
        Add this to <code>CLAUDE.md</code> in your repo root (committed, shared with the team) or
        <code> ~/.claude/CLAUDE.md</code> (personal, all projects). Claude Code loads it into context every session:
      </p>
      <pre><code>{ruleFileFor("claude").content}</code></pre>

      <h3>Cursor</h3>
      <p>
        Create <code>.cursor/rules/cognivio.mdc</code> with <code>alwaysApply: true</code> so the rule is in
        context on every request (you can also add it under <b>Settings → Rules</b>). Without the frontmatter Cursor
        treats it as a manual rule and won't load it every turn, which is why the discipline can silently lapse
        across a multi-task session:
      </p>
      <pre><code>{ruleFileFor("cursor").content}</code></pre>
      <p>
        Codex users: the same body goes in <code>AGENTS.md</code> (<code>setup_rule</code> emits it for you).
      </p>

      <h2 id="workflow">Recommended agent workflow</h2>
      <ul>
        <li><b>Prime:</b> call <code>prime_context("the task")</code> (or <code>/context?q=…</code>) first, one call returns the index + the most relevant docs as excerpts.</li>
        <li><b>Orient (if needed):</b> <code>read_map</code> for the full graph of a team.</li>
        <li><b>Search:</b> use <code>search_memory</code> with a focused query and an optional <code>type</code>.</li>
        <li><b>Read:</b> pull full content with <code>get_memory</code>; follow connections with <code>get_related</code>.</li>
        <li><b>Write back:</b> after solving something, capture a <code>lesson</code> or <code>incident</code> with
          <code>write_memory</code> so the next agent starts ahead. Reference other docs with <code>[[Title]]</code>.</li>
      </ul>

      <h2 id="coverage">Make your KB actually help</h2>
      <p>
        The payoff is real but conditional: an agent benefits when your docs <b>cover the part of the
        system the task touches</b>. A thin or stale KB just adds overhead. Two habits keep it earning its keep:
      </p>
      <p>
        <b>First time? Let your agent seed it.</b> Once connected, just ask it to "seed our Cognivio knowledge base",
        it calls <code>seed_plan</code> for a ready-made plan (what already exists, which areas have no docs, whether
        writes need review) and then scans the repo and writes the starter docs. Or paste this prompt to be explicit
        (also offered in the <b>Connect a tool</b> dialog):
      </p>
      <pre><code>{`Set up our Cognivio knowledge base for THIS repository.
1. Call list_teams to find the team id to write to.
2. Scan the repo (README, structure, key modules/files).
3. With write_memory, create docs IN THIS ORDER so their links resolve: first a
   "decision" doc per non-obvious choice; then an "architecture" doc "How It Works"
   citing real files/classes; LAST a "map" titled "<Project> Map" tagged ["index"]
   linking the rest with [[Exact Title]]. Keep each concise, and don't put example
   [[bracket]] syntax in a body (it's parsed as a real link).
4. List what you created.`}</code></pre>
      <ul>
        <li><b>Document where agents work.</b> Start with a <b>Project Map</b> plus a short "How It Works"
          and the key <b>Decisions</b> for the areas you actually change. Breadth beats polish, a few
          accurate docs with real file/class names beat one perfect essay.</li>
        <li><b>Close the gaps it reveals.</b> When an agent searches for something you haven't documented,
          it's recorded, call <code>knowledge_gaps</code> (or check <b>Agents → Activity</b>) to see the
          top misses, then write those docs. Gap → doc → win.</li>
        <li><b>Keep it fresh.</b> After a non-obvious change, have the agent <code>write_memory</code> (writing an
          existing title <em>updates</em> that doc, no duplicates) so the KB tracks the code. Each doc shows a
          <em>last-verified</em> date, the Docs list has a <b>⚠ Stale</b> filter, and the agent can run
          <code>check_drift</code> from the repo to catch docs whose referenced code changed since they were verified.</li>
      </ul>

      <h2 id="repo">Repo coverage &amp; drift</h2>
      <p>
        Connect a team's Git repo (read-only) under the <b>Repo</b> tab to turn "you haven't documented X" into something
        you can see. It runs server-side, so the Remote MCP <code>check_drift</code> tool works with no local setup; the
        local stdio connector's <code>check_drift</code> diffs your working tree instead.
      </p>
      <ul>
        <li><b>Connect:</b> pick <b>GitLab</b> or <b>GitHub</b>, enter the <b>project path</b> (the part of the repo URL
          after the host, no <code>.git</code>, e.g. <code>group/project</code> or <code>owner/repo</code>), and a
          <b> read-only</b> token. GitLab needs the <code>read_api</code> scope (<em>not</em> <code>read_repository</code>,
          which is Git-clone only); GitHub needs <code>repo</code> (classic) or <code>Contents: read</code> +
          <code> Metadata: read</code> (fine-grained). The token is stored to call the API and never shown again. Leave
          <b> Base URL</b> blank unless you're on self-hosted GitLab / GitHub Enterprise.</li>
        <li><b>Coverage:</b> a file counts as <em>covered</em> when a doc cites its <b>exact path</b> (e.g.
          <code> backend/app/main.py</code>). The per-directory breakdown is ranked least-covered first, those are areas
          agents work in that nobody has written up. Low overall coverage is expected; it's a map of where to look, not a
          score. Raise it by writing docs that cite real file paths.</li>
        <li><b>Drift:</b> a doc is flagged as <em>drifted</em> when it cites a file whose latest commit is newer than the
          doc's last <b>Verify</b>. Open it, re-read the changed file, update the doc, and hit <b>Verify</b> to clear it.</li>
        <li><b>Refresh</b> re-scans on demand. Only org owners/admins can connect or disconnect a repo.</li>
      </ul>

      <h2 id="human-api">Human auth (reference)</h2>
      <p>
        People sign in through the UI, but the underlying endpoints are <code>POST /api/auth/register</code>,
        <code>POST /api/auth/login</code> (returns a 30-minute JWT), and <code>GET /api/auth/me</code>. Registration
        automatically creates your organization, a <b>Main</b> team, and an owner membership, so you can start
        writing immediately, no setup required.
      </p>
    </div>
  );
}
