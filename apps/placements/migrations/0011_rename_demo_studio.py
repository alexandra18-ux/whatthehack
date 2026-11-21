from django.conf import settings
from django.db import migrations


def rename_demo_studio(apps, schema_editor):
    user_model = apps.get_model(settings.AUTH_USER_MODEL)
    users = user_model.objects.using(schema_editor.connection.alias)
    if not users.filter(username="Murrralium Studio").exists():
        users.filter(username="Muralium Studio", password__startswith="!").update(username="Murrralium Studio")


class Migration(migrations.Migration):
    dependencies = [("placements", "0010_existing_graffiti_photo")]

    operations = [migrations.RunPython(rename_demo_studio, migrations.RunPython.noop)]
