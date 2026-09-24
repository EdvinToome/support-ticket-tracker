from django.db import migrations, models


def backfill_updated_at(apps, schema_editor):
    for model_name in ("Customer", "Comment"):
        model = apps.get_model("tickets", model_name)
        model.objects.using(schema_editor.connection.alias).update(
            updated_at=models.F("created_at")
        )


class Migration(migrations.Migration):
    dependencies = [("tickets", "0004_attachment_limit_3mib")]

    operations = [
        migrations.AddField(
            model_name="customer",
            name="updated_at",
            field=models.DateTimeField(null=True),
        ),
        migrations.AddField(
            model_name="comment",
            name="updated_at",
            field=models.DateTimeField(null=True),
        ),
        migrations.RunPython(backfill_updated_at, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="customer",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AlterField(
            model_name="comment",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
    ]
