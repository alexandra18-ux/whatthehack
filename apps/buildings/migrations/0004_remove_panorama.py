from django.db import migrations


def check_panorama_data(apps, schema_editor):
    db = schema_editor.connection.alias
    Panorama = apps.get_model("buildings", "Panorama")
    FacadePhoto = apps.get_model("buildings", "FacadePhoto")
    if (
        Panorama.objects.using(db).exists()
        or FacadePhoto.objects.using(db).filter(panorama_id__isnull=False).exists()
    ):
        raise RuntimeError(
            "Legacy panoramas or facade links still exist. Review and preserve this data before removing the panorama schema."
        )


class Migration(migrations.Migration):
    dependencies = [
        ("buildings", "0003_panorama_facadephoto_panorama"),
        ("placements", "0009_remove_estate_demo"),
    ]

    operations = [
        migrations.RunPython(check_panorama_data, migrations.RunPython.noop),
        migrations.RemoveField(model_name="facadephoto", name="panorama"),
        migrations.DeleteModel(name="Panorama"),
    ]
