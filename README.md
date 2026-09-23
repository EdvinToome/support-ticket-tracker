# Support Ticket Tracker

A small support queue built on Django 5.2 admin. It shows customer and ticket relationships, multiple agent assignments, enforced ticket transitions, role-based access, private attachments, and AI help grounded in the form a staff member can see.

Demo: [live admin](https://support-ticket-tracker-extb.onrender.com/admin/) · [source repository](https://github.com/EdvinToome/support-ticket-tracker). Reviewer credentials are supplied privately. The first request may take about a minute while the free Render service wakes.

## Run locally

Requires Python 3.12, [uv](https://docs.astral.sh/uv/), and Docker. The example environment is for local development only.

```bash
cp .env.example .env
docker compose up -d
uv sync --frozen
uv run --env-file .env python manage.py migrate
uv run --env-file .env python manage.py createcachetable
uv run --env-file .env python manage.py createsuperuser
uv run --env-file .env python manage.py seed_demo
uv run --env-file .env python manage.py runserver
```

Open <http://127.0.0.1:8000/admin/> and sign in with the superuser you created. The seed creates 200 customers, 20 agent profiles, 2,000 tickets, 6,000 comments, and 50 synthetic attachments by default. Seeded agent users have unusable passwords. To try the three roles, create ordinary users in admin, set `is_staff`, and assign each to the `Admin`, `Agent`, or `Viewer` group. Create an Agent profile for a login that should appear in ticket assignment choices; a group membership alone does not make a user assignable.

For a smaller dataset, pass `--customers`, `--agents`, `--tickets`, `--comments`, and `--attachments` counts to `seed_demo`. A second seed without `--reset` fails if domain data exists. **`seed_demo --reset` deletes every customer, ticket, comment, attachment, and Agent profile, then replaces the dataset.** It deletes users whose names start with `seed-`; other login users and role groups remain. Recreate Agent profiles for any retained logins that need assignments. Old attachments are deleted only after the database transaction commits. New uploads are not transactional, so a failed seed may leave unreferenced objects to clean up.

```bash
uv run --env-file .env python manage.py seed_demo --reset
```

## Work in the admin

| Capability | Admin | Agent | Viewer |
| --- | --- | --- | --- |
| View tickets, comments, customers, and agent directory | Yes | Yes | Yes |
| Add or change tickets and comments; resolve selected tickets | Yes | Yes | No |
| Add customers | Yes | Yes | No |
| Change customers or agent profiles; delete business records | Yes | No | No |
| Manage ordinary users and assign role groups | Yes | No | No |
| Ask about visible Ticket and Customer forms | Yes | Yes | Yes |

Role permissions are created by a data migration. Non-superuser Admins cannot edit superuser accounts, set `is_superuser`, grant direct user permissions, or change role definitions. New login users need `is_staff=True` as well as a group. The Agent profile is an assignment roster entry, not a source of login permission.

Tickets begin **Open**. They can move among Open, In progress, and Resolved, or be closed directly. A ticket cannot enter Resolved until it has a **saved** comment. When adding the first inline comment, use **Save and continue editing**, then set Resolved. Closed tickets cannot reopen, although other fields can still be edited. `Ticket.save()` validates these rules; the bulk resolve path uses the same transition function.

The Ticket list sorts by highest priority, then oldest, and includes comment count and last activity. It has status, priority, assignee, **Assigned to me**, and **Unassigned** filters. **Resolve selected tickets** resolves eligible rows, leaves already-resolved rows unchanged, and reports closed or comment-less rows as skipped. It shows up to 10 ticket IDs per skip reason and records admin log entries for resolved tickets. The action runs in one database transaction; a mixed selection can succeed in part.

Attachments accept PDF, PNG, and JPEG up to 5 MiB each, with a 10 MiB request limit. Validation checks extension and content; private S3 objects are served through signed, short-lived attachment URLs. The signed URL explicitly requests attachment disposition for consistent downloads from Supabase. WhiteNoise serves static files only.

The **Ask about this form** panel appears on Ticket and Customer add/change pages, including read-only pages a Viewer may access. It sends the question and server-derived field names, types, required flags, choices, help text, and read-only state to OpenAI. It does not send saved ticket/customer values or enumerate relationship choices. Answers are displayed as plain text; it cannot edit records. The integration uses the paid `gpt-6-luna` Responses API with no reasoning, no tools, `store=False`, a 1,000-character question limit, 500 output tokens, a 10-second timeout, and no SDK retries. Missing keys and provider failures leave the admin usable and return a clear unavailable message.

## Test and deploy

Tests use the local PostgreSQL service, in-memory attachment storage, a local-memory cache, and mocked AI calls. `config.test_settings` rejects non-local database hosts; tests do not connect to Supabase.

```bash
uv run --env-file .env pytest
uv run --env-file .env ruff check .
uv run --env-file .env ruff format --check .
uv run --env-file .env python manage.py makemigrations --check --dry-run
uv run --env-file .env python manage.py collectstatic --noinput
```

`render.yaml` defines a free Render web service. The build installs locked dependencies and collects static files. Startup runs migrations and `createcachetable`, then starts Gunicorn with two workers and four threads. Set the listed environment variables in Render; do not use the local example credentials. Use the **actual Supabase session-pooler PostgreSQL URL** (port 5432, SSL in production) for `DATABASE_URL`. Create a **private** Supabase Storage bucket, configure its S3 endpoint, region, bucket, access key, and secret, and disable the unused Supabase Data API. Set Render's `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` to the deployed host/origin. `OPENAI_API_KEY` is optional for ordinary admin work; the AI panel reports unavailable when it is absent. Set any OpenAI project budget or alerts separately: this application does not change that project's controls, and a budget alert is not a hard spending cap.

After deployment, seed once from a trusted local machine with production variables in an uncommitted environment file; the Render startup script does **not** seed:

```bash
uv run --env-file .env.production python manage.py seed_demo
uv run --env-file .env.production python manage.py check --deploy
```

`/healthz` runs `SELECT 1` and returns `ok` when the database is reachable. A database `OperationalError` produces a static 503 page. For a 500, check Render's stdout logs first, then `/healthz` to separate application errors from database availability. Dropped pooled connections are health-checked on the next request; a write interrupted by a database error rolls back. Render free services can cold-start, so the first request may be slow.

The GitHub keep-alive workflow calls `/healthz` daily when the repository variable `DEMO_URL` is set to the deployed base URL. **Supabase free projects may pause after a week of inactivity.** The keep-alive is best effort: [Supabase requires sufficient user database activity](https://supabase.com/docs/guides/platform/free-project-pausing), so one daily query is not guaranteed to prevent pausing. Resume a paused project in Supabase's dashboard. [GitHub disables scheduled workflows in inactive public repositories after 60 days](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows); re-enable the workflow if needed.

## Design boundaries

Django admin supplies authentication, forms, permissions, and an audit trail without a separate frontend. PostgreSQL enforces relationships, case-insensitive customer email uniqueness, and valid status/priority choices. Supabase hosts the database and private media; Render runs the app; WhiteNoise serves static assets. The four domain models are Customer, Agent, Ticket, and Comment. Multiple Agent profiles can be assigned to a ticket.

The ticket transition rule is enforced by normal model saves and the bulk action, not by a database trigger. Raw SQL or unrelated bulk updates could bypass it. A stale single-ticket edit has a brief window between reading its persisted status and writing; the bulk action locks selected rows. At higher traffic, inspect session-pooler connection limits and worker memory before increasing worker count. The AI limiter uses shared `DatabaseCache` counters (5 requests per user per minute, 200 per day globally); increments are not atomic, so concurrent requests can slightly exceed a limit. The cache survives app worker restarts.

An admin session lasts eight hours. A stolen active session grants the permissions of that login until it expires or is revoked. The public admin has no login-attempt throttling. There is no customer portal, OAuth, email notification, SLA system, dashboard, background job, vector search, AI write access, streaming, or stored AI chat history. Full malware scanning and automatic cleanup of orphaned S3 objects are deferred. OAuth users, if added later, should receive no group until an Admin assigns one. Login throttling, stronger storage cleanup, and a row lock for individual ticket edits are natural next steps.
