from django.db import migrations


def create_roles(apps, schema_editor):
    database = schema_editor.connection.alias
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")
    grants = {"Admin": [], "Agent": [], "Viewer": []}
    for app_label, model_name in [
        ("tickets", "customer"),
        ("tickets", "agent"),
        ("tickets", "ticket"),
        ("tickets", "comment"),
        ("auth", "user"),
    ]:
        content_type, _ = ContentType.objects.using(database).get_or_create(
            app_label=app_label,
            model=model_name,
        )
        for action in ("view", "add", "change", "delete"):
            permission, _ = Permission.objects.using(database).get_or_create(
                content_type=content_type,
                codename=f"{action}_{model_name}",
                defaults={"name": f"Can {action} {model_name}"},
            )
            grants["Admin"].append(permission)
            if app_label == "tickets":
                if action == "view":
                    grants["Viewer"].append(permission)
                    grants["Agent"].append(permission)
                elif action in {"add", "change"} and model_name in {"ticket", "comment"}:
                    grants["Agent"].append(permission)
                elif action == "add" and model_name == "customer":
                    grants["Agent"].append(permission)
    for name, permissions in grants.items():
        group, _ = Group.objects.using(database).get_or_create(name=name)
        group.permissions.set(permissions)


def remove_roles(apps, schema_editor):
    apps.get_model("auth", "Group").objects.using(schema_editor.connection.alias).filter(
        name__in=["Admin", "Agent", "Viewer"],
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("tickets", "0001_initial"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]
    operations = [migrations.RunPython(create_roles, remove_roles)]
