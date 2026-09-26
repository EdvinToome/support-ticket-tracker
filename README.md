# Support Ticket Tracker

A support desk built on the Django admin: tickets, customers, agents and comments with attachments, three roles, and an AI assistant for the admin forms.

- **Live:** <https://support-ticket-tracker-flame.vercel.app/admin/> (logins for each role are provided separately)
- **Code:** <https://github.com/EdvinToome/support-ticket-tracker>

The demo has 200 customers, 20 agents, 2,000 tickets, 6,000 comments and 50 attachments.

## What to try

- **Ticket list:**
  - Search by ticket ID, subject, or customer name or email.
  - Filter by status, priority or assigned agent.
  - In-progress and open tickets come first, then high priority, then oldest.
- **Comments:** add them at the bottom of a ticket. Each comment can have a PDF, PNG or JPEG attached.
- **Resolving:** a ticket needs a saved comment first. Add the comment, click *Save and continue editing*, then set the status to Resolved.
- **Closed tickets:** can't be reopened or edited, but you can still add comments.
- **Bulk resolve:** select tickets in the list and run *Resolve selected tickets*. Closed tickets and tickets without comments are skipped, and the message says which ones and why.
- **AI assistant:** click the chat button in the bottom-right corner. Use *Help with this form* to explain fields and errors, or *Summarize record* for the ticket, customer or agent you have open.

## Roles

| Role | Can do |
| --- | --- |
| Admin | Everything, including managing user accounts. Can't create superusers or change what a role allows. |
| Agent | See everything, add customers, and add and edit tickets and comments. Can't delete anything. |
| Viewer | Read only, plus the AI assistant. |

Roles are Django groups. The admin hides every menu and button a role can't use.

## Run locally

You need Python 3.12, [uv](https://docs.astral.sh/uv/) and Docker. Docker runs Postgres and MinIO (local S3 storage).

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

Open <http://127.0.0.1:8000/admin/> and sign in with the superuser you created.

- **Other roles:** create a staff user and add it to the Admin, Agent or Viewer group.
- **Reset:** `seed_demo --reset` deletes all tickets, customers, comments and attachments, then seeds again. Users you created are kept.
- **AI assistant:** add an `OPENAI_API_KEY` to `.env`. The rest of the app works without it.

## Why this stack

- **Django admin:** login, permissions, list views, filters, inlines and bulk actions come built in, so my own code is only the support workflow.
- **Supabase:** one free project gives both managed Postgres and S3-compatible file storage.
- **Vercel:** free hosting with HTTPS, a deploy on every push, and static files served from a CDN. It rejects requests over 4.5 MB, so one save can upload at most 4 MiB in total and 3 MiB per file.
- **OpenAI `gpt-6-luna`:** fast, cheap and nothing to host. It's paid, so I limit it to 5 questions per user per minute and 200 a day for the whole site.

## How it works

- **Models:**
  - A customer has many tickets.
  - A ticket can be assigned to several agents and has many comments.
  - A comment can have one attachment.
  - An agent is a profile attached to a Django user.
- **Workflow rules are in `models.py`.** `Ticket.save()` validates before writing, and the bulk action checks the same rule function.
- **The database rejects bad data too.** Status and priority must be known values. Two customers can't share an email address, even with different capitalization.
- **Bulk resolve** locks the selected tickets while it runs, resolves the eligible ones in one query, and adds each change to the admin history.
- **Uploads:**
  - The app reads each file to check its type, not only the extension.
  - Files are held in memory, never written to the server's disk, and stored in a private bucket.
  - Download links expire after five minutes and always download rather than open in the browser.
- **AI assistant:**
  - It receives the form's fields and `help_text`, what the user has typed, any errors, and the open record's direct relations (for a ticket: its customer, agents and comments).
  - It only sees what that user is allowed to view, and it can't change data.
- **Missing settings stop the app from starting.** It never falls back to a local database or local disk. `/healthz` returns 503 if the database is unreachable.

## Tests

Start the Docker services first, then run:

```bash
uv run --env-file .env pytest -q
```

The nine tests cover:
- the workflow rules and bulk resolve;
- closed tickets;
- upload errors;
- what the AI assistant can see.

OpenAI is mocked. CI also runs Ruff, checks for missing migrations, and runs `collectstatic`.

## Deploy

1. Import the repo into Vercel with the Django preset.
2. Set every variable from `.env.example` to its production value, with `DJANGO_DEBUG=False`. Each build runs the migrations.
3. To load demo data, run `seed_demo` once from your machine with the production database and storage settings. Deploys never reseed.

Supabase pauses free projects after a week with no activity. A daily GitHub Action calls `/healthz` to keep the project active. It runs once you set the `DEMO_URL` repository variable.

## What I left out

- **OAuth login:** optional in the brief. Django's own login already meets the security requirements.
- **Customer portal, email notifications and SLAs:** the brief asks for an internal admin tool.
- **AI that edits records:** the brief asks for help with forms. An assistant that can't write can't corrupt data.

## With more time

- Limit repeated failed logins.
- Stop two people editing the same ticket from overwriting each other's changes.
- Make the AI usage limits exact. Today two simultaneous requests can both get through at the limit.
- Scan uploads for malware, and delete stored files that no comment uses anymore.
