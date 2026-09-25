# Support Ticket Tracker

A Django 5.2 admin application for managing support tickets, with role-based access, private attachments and contextual AI help.

**[Live demo](https://support-ticket-tracker-flame.vercel.app/admin/)** · **[Source](https://github.com/EdvinToome/support-ticket-tracker)**

Admin, Agent and Viewer credentials are supplied privately. The demo has roughly 200 customers, 20 agents, 2,000 tickets, 6,000 comments and 50 sample attachments.

## Try it

- Search by ticket ID, subject or customer; filter by status, priority or assignment. Default order: **In progress → Open → Resolved → Closed**, then highest priority and oldest first.
- Add a comment inline. To resolve a ticket with its first comment, keep it Open/In progress and use **Save and continue editing**, then change its status to Resolved. The comment must already be saved.
- Try **Resolve selected tickets**. Eligible tickets resolve; closed tickets and those without comments are skipped, with counts and audit entries.
- Close a ticket: its details become read-only, while comments remain available.
- Open the floating **AI assistant** for field/validation help or a summary of the current record.

| Role | Permissions |
| --- | --- |
| Admin | Manage business records and ordinary users; cannot grant superuser access or alter role definitions. |
| Agent | View business records; add customers; add/edit tickets and comments; bulk resolve. No deletions or user management. |
| Viewer | Read-only access and AI help. |

## Run locally

Requires Python 3.12, [uv](https://docs.astral.sh/uv/) and Docker. Docker provides PostgreSQL and MinIO object storage.

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

Sign in at <http://127.0.0.1:8000/admin/>. To test another role, create a user with `is_staff=True` and assign its Group. An Agent profile makes that user assignable to tickets. Seeded users have unusable passwords.

Use `seed_demo --help` to adjust counts. **`seed_demo --reset` replaces all customers, tickets, comments and attachments, plus seeded users/profiles.** Other users and their Agent profiles remain.

## Design decisions

- **Django admin** supplies authentication, hashed passwords, sessions, CSRF protection, permissions and forms. Custom code concentrates on the support workflow.
- **Four domain models:** Ticket belongs to Customer, has many Agent assignees, and has Comment children with optional attachments. Agent links one-to-one to a Django user. Customer, Ticket and Comment share an abstract `TimestampedModel`.
- **Supabase** supplies managed PostgreSQL through its session pooler and private S3-compatible storage through `django-storages`. The database enforces relationships, valid status/priority values and case-insensitive customer email uniqueness. Model-layer workflow validation is shared with the bulk action.
- **Vercel Hobby** runs Django as a Python function and serves static files through its CDN; WhiteNoise supports local runs. Hosting stays small, with function cold starts and upload limits as trade-offs.

Attachments accept PDF, PNG and JPEG up to **3 MiB per file / 4 MiB per request**. Uploads stay in memory until sent to storage; downloads use signed, five-minute URLs. Failed validation preserves file selections for retry; refreshing or navigating away clears them.

## AI help

OpenAI receives actual field definitions, choices and `help_text`, current inputs/errors, and the selected record's permitted direct relationships. Saved values and unsaved changes are identified separately. Only attachment filenames are included. The assistant cannot modify records or send customer messages.

Set `OPENAI_API_KEY` to enable it; ordinary admin work does not require a key. It uses paid `gpt-6-luna`, a 10-second timeout, 500 output tokens and a 1,000-character question limit. Provider failures display an unavailable message. Approximate shared limits allow five requests per user per minute and 200 per day. Increments are not atomic; large related-record collections increase input cost.

## Tests and deployment

```bash
uv run --env-file .env pytest -q
uv run ruff check .
```

Nine tests cover workflow rules, bulk resolution, closed-ticket editing, attachment retries and AI context/permissions. Tests use local PostgreSQL and mock OpenAI. CI also checks formatting, migration consistency and static collection.

Import the repository into Vercel using the **Django** preset. Configure the keys in `.env.example` with production values: debug off, a strong secret key, exact allowed host/HTTPS origin, Supabase session-pooler URL and private S3 credentials. `TEST_DATABASE_URL` is local-only. Missing required configuration stops startup; there is no local-storage fallback.

Builds apply migrations, create the shared cache table and collect static files. Seed production once from a trusted machine using an uncommitted environment file; deployment does not reseed. `/healthz` checks database connectivity; use Vercel Runtime Logs to investigate failures.

**Supabase free projects may pause after a week of inactivity.** The daily health-check workflow is best effort, not a guarantee against pausing.

## Scope and limitations

Single-ticket saves validate the current status but do not lock the row, so simultaneous edits can race. The bulk action locks its selected rows. Public login has no throttling; sessions expire after eight hours.

I left out OAuth, a customer portal, email notifications, SLAs and AI write access to keep the submission focused on the admin workflow. With more time, I would add login throttling, protect single-ticket saves against concurrent edits, make AI limits atomic, and add malware scanning/orphaned-file cleanup.
