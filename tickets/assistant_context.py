"""Build model inputs from one ticket and its own saved attachments."""

import json
from pathlib import Path

from django.utils import timezone


def ticket_input_content(ticket):
    comments = list(ticket.comments.select_related("author").order_by("created_at", "pk"))
    now = timezone.now()
    last_activity = max([ticket.updated_at, *(comment.created_at for comment in comments)])
    context = {
        "id": ticket.pk,
        "subject": ticket.subject,
        "description": ticket.description,
        "status": ticket.get_status_display(),
        "priority": ticket.get_priority_display(),
        "assignees": [str(agent) for agent in ticket.assignees.all()],
        "as_of": now.isoformat(),
        "created_at": ticket.created_at.isoformat(),
        "last_activity_at": last_activity.isoformat(),
        "age_days": (now - ticket.created_at).days,
        "days_since_activity": (now - last_activity).days,
        "comments": [
            {
                "id": comment.pk,
                "date": comment.created_at.isoformat(),
                "author": comment.author.get_username(),
                "body": comment.body,
            }
            for comment in comments
        ],
    }
    content = [{"type": "input_text", "text": "Saved ticket data:\n" + json.dumps(context)}]
    for comment in comments:
        if not comment.attachment:
            continue
        extension = Path(comment.attachment.name).suffix.lower()
        content.append(
            {
                "type": "input_text",
                "text": f"Comment #{comment.pk} attachment ({extension[1:].upper()}):",
            }
        )
        url = comment.attachment.url
        if extension == ".pdf":
            content.append({"type": "input_file", "file_url": url})
        else:
            content.append({"type": "input_image", "image_url": url, "detail": "auto"})
    return content
