# Support Ticket Tracker

A small support queue built on Django 5.2 admin. It shows customer and ticket relationships, multiple agent assignments, enforced ticket transitions, role-based access, private attachments, and AI help grounded in the form a staff member can see.

Demo: [live admin](https://support-ticket-tracker-flame.vercel.app/admin/) · [source repository](https://github.com/EdvinToome/support-ticket-tracker). Reviewer credentials are supplied privately. Hosted on Vercel Hobby. A Python function may cold-start on the first request; there is no Render wake-up page.

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

For a smaller dataset, pass `--customers`, `--agents`, `--tickets`, `--comments`, and `--attachments` counts to `seed_demo`. A second seed without `--reset` fails if demo data exists. **`seed_demo --reset` deletes every customer, ticket, comment, and attachment, plus the seeded `seed-` users and their Agent profiles, then recreates the dataset.** Other logins, their Agent profiles, and the role groups remain. Old attachments are deleted only after the database transaction commits. New uploads are not transactional, so a failed seed may leave unreferenced objects to clean up.

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
| Summarize tickets and draft customer replies | Yes | Yes | Yes |

Role permissions are created by a data migration. Non-superuser Admins cannot edit superuser accounts, set `is_superuser`, grant direct user permissions, or change role definitions. New login users need `is_staff=True` as well as a group. The Agent profile is an assignment roster entry, not a source of login permission.

Tickets begin **Open**. They can move among Open, In progress, and Resolved, or be closed directly. A ticket cannot enter Resolved until it has a **saved** comment. When adding the first inline comment, use **Save and continue editing**, then set Resolved. Closed tickets cannot reopen, although other fields can still be edited. `Ticket.save()` validates these rules; the bulk resolve path uses the same transition function.

The Ticket list sorts by highest priority, then oldest, and includes ticket ID, comment count, and last activity. Numeric searches match an exact ticket ID; other searches match subject or customer name/email. It has status, priority, assignee, **Assigned to me**, and **Unassigned** filters. **Resolve selected tickets** resolves eligible rows, leaves already-resolved rows unchanged, and reports closed or comment-less rows as skipped. It shows up to 10 ticket IDs per skip reason and records admin log entries for resolved tickets. The action runs in one database transaction; a mixed selection can succeed in part.

Attachments accept PDF, PNG, and JPEG up to 3 MiB each; oversized or mismatched files are reported as form errors. Uploads are buffered in memory, never on local disk, and requests over 4 MiB are refused outright. Private S3 objects are served through signed, five-minute URLs that force a download rather than inline display. Vercel serves collected static files through its CDN; WhiteNoise remains compatible with local runs.

The **Ticket assistant** is a compact floating chat available throughout the logged-in admin to users who can view tickets. It leaves the page interactive and offers two actions: **Summarize ticket** (issue, progress, unresolved points) and **Draft reply** (customer-facing text to review and copy). Opening a saved ticket selects it automatically; elsewhere, find a ticket by title or number. Follow-up messages can refine a summary or reply. Changing tickets starts a new conversation. The chat survives navigation in the same browser tab using session storage, scoped to the logged-in user. It never saves comments, changes tickets, or sends messages to customers.

The server checks ticket permissions and sends the selected ticket's saved subject, description, status, priority, and dated comment bodies to OpenAI. Unsaved edits, attachment contents, customer contact fields, and other tickets are not included. Replies display as plain text. The paid `gpt-6-luna` Responses API uses no reasoning or tools, `store=False`, a 1,000-character message limit, the last six conversation messages, 500 output tokens, a 10-second timeout, and no SDK retries. The existing five-per-user/minute and 200-global/day approximate rate limits remain. Missing keys and provider failures return an explicit unavailable message. This ticket-focused scope replaces the brief's form-definition help bonus; form help is not implemented.

## Test and deploy

The suite has nine cases: resolving requires a saved comment, new tickets cannot start resolved, closed tickets cannot reopen (three destinations), stale edits respect a later closure, bulk resolution handles a mixed selection and reports/logs the result, and two assistant tests cover ticket access and the data sent by both actions without writing records. Tests use local PostgreSQL and an HTTP transport stub for OpenAI; they do not connect to Supabase or the real provider.

```bash
uv run --env-file .env pytest
uv run --env-file .env ruff check .
uv run --env-file .env ruff format --check .
uv run --env-file .env python manage.py makemigrations --check --dry-run
uv run --env-file .env python manage.py collectstatic --noinput
```

Import the GitHub repository into a **Vercel Hobby** project using the **Django** preset. `vercel.json` selects Paris (`cdg1`), a 30-second function timeout, and a build command that applies migrations and creates the shared cache table. Vercel installs dependencies from `pyproject.toml`/`uv.lock`, discovers `config.wsgi.application`, and automatically runs `collectstatic`. `.python-version` selects Python 3.12. There is no persistent application server or startup migration command.

Configure production environment variables using `.env.example` as the key list; `TEST_DATABASE_URL` is local-only. Set `DJANGO_DEBUG=False`, a strong `SECRET_KEY`, the exact deployment host in `ALLOWED_HOSTS`, and its HTTPS origin in `CSRF_TRUSTED_ORIGINS`. Use the **actual Supabase session-pooler PostgreSQL URL** (port 5432, SSL in production) for `DATABASE_URL`. Keep the existing **private** bucket and S3 endpoint, region, bucket name, access key, and secret. The unused Supabase Data API is disabled. Production credentials are scoped to Production; preview deployments need their own configuration.

`OPENAI_API_KEY` is optional for ordinary admin work; the AI panel reports unavailable when it is absent. Set any OpenAI project budget or alerts separately: this application does not change that project's controls, and a budget alert is not a hard spending cap. Never commit environment files. Upload limits leave room below Vercel's 4.5 MB request-payload limit.

After deployment, seed once from a trusted local machine with production variables in an uncommitted environment file; deployments do **not** seed:

```bash
uv run --env-file .env.production python manage.py seed_demo
uv run --env-file .env.production python manage.py check --deploy
```

`/healthz` runs `SELECT 1` and returns `ok` when the database is reachable. A database `OperationalError` produces a static 503 page. For a 500, check Vercel's Runtime Logs first, then `/healthz` to separate application errors from database availability. Django closes its database connection after each request; Supabase handles pooling. A write interrupted by a database error rolls back. Vercel functions can cold-start, so the first request may be slower than warm requests.

The GitHub keep-alive workflow calls `/healthz` daily when the repository variable `DEMO_URL` is set to the deployed base URL. **Supabase free projects may pause after a week of inactivity.** The keep-alive is best effort: [Supabase requires sufficient user database activity](https://supabase.com/docs/guides/platform/free-project-pausing), so one daily query is not guaranteed to prevent pausing. Resume a paused project in Supabase's dashboard. [GitHub disables scheduled workflows in inactive public repositories after 60 days](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows); re-enable the workflow if needed.

## Why this stack

- **Django admin.** The brief asks for a generated admin, not a hand-built UI. Django's admin already provides password hashing, sessions, CSRF protection, per-model permissions and groups, list filters, search, inlines, bulk actions, and an audit log, so the work here is configuration and business rules rather than plumbing. Rails with ActiveAdmin or Laravel with Filament would also generate an admin; Django keeps roles, permissions, and the admin in one framework with no extra packages.
- **PostgreSQL on Supabase.** A managed free-tier database, and the same project provides private S3-compatible storage, so the demo depends on one data provider. The session pooler gives an IPv4 endpoint that suits Django's persistent connections.
- **Vercel Hobby.** Native Django support runs the app as a Python function and serves static files through its CDN. This removes Render's free-tier wake-up screen. The trade-offs are possible function cold starts, platform usage quotas, and a 4.5 MB request limit. Hobby is for personal, non-commercial use.
- **OpenAI `gpt-6-luna`.** A small, low-cost paid model used with an existing API key. The 500-token answer cap and the 200-requests-per-day limit keep spend to cents per day. A free-tier provider would also work; only `ask_form_question` would change.

The four domain models are Customer, Agent, Ticket, and Comment. Ticket has a customer foreign key, a many-to-many `assignees` relation to Agent profiles, and comments with optional attachments.

## Trade-offs

- **Resolving takes two saves.** A ticket needs a *saved* comment before it can be Resolved, so the first inline comment is saved with **Save and continue editing**. Counting unsaved inline comments would need a custom admin save pipeline.
- **The workflow rule lives in Python, not a trigger.** `Ticket.save()` and the bulk action share one transition function, which keeps the rule readable and tested; raw SQL could bypass it. PostgreSQL still enforces relationships, case-insensitive customer email uniqueness, and valid status/priority values.
- **Single-ticket edits are not locked.** A stale edit has a brief window between reading the saved status and writing. The bulk action does lock its rows.
- **Approximate rate limits.** The AI limits (5 per user per minute, 200 per day) use `DatabaseCache` counters, so they are shared across function instances and survive restarts without Redis. Increments are not atomic, so simultaneous requests can slightly exceed a limit.
- **Sessions last eight hours.** A stolen active session grants that login's permissions until it expires or is revoked.

Deliberately left out: a customer portal, OAuth, email notifications, SLAs, dashboards, background jobs, streaming or stored AI chat, and AI write access. Each adds surface without showing anything the admin, roles, and workflow don't already show.

## With more time

- Login throttling on the public admin (for example django-axes); there is none today.
- A row lock for single-ticket edits to close the stale-edit window.
- Malware scanning for uploads and automatic cleanup of orphaned S3 objects.
- An atomic, shared rate limiter (Redis) and a look at session-pooler connection limits before increasing concurrency.
- OAuth sign-in, with new users getting no group until an Admin assigns one.
