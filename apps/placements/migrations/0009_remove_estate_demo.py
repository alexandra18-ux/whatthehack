from django.db import migrations


def remove_estate_demo(apps, schema_editor):
    db = schema_editor.connection.alias
    Building = apps.get_model("buildings", "Building")
    Panorama = apps.get_model("buildings", "Panorama")
    FacadePhoto = apps.get_model("buildings", "FacadePhoto")
    Placement = apps.get_model("placements", "Placement")
    buildings = Building.objects.using(db).filter(
        address="Усадьба Шмидта · улица Радищева, 14",
        latitude="51.525549",
        longitude="46.033877",
        osm_ref__isnull=True,
    )
    for building in buildings:
        demo_panoramas = Panorama.objects.using(db).filter(
            building=building,
            title="Двор усадьбы Шмидта",
            credit="FingerWiki",
            source_url=(
                "https://commons.wikimedia.org/wiki/"
                "File:Courtyard_of_the_P._P._Schmidt_Estate_in_Saratov,_21_September_2020.jpg"
            ),
        )
        if not demo_panoramas.exists():
            continue
        used_panoramas = FacadePhoto.objects.using(db).filter(
            panorama_id__in=demo_panoramas,
        ).values("panorama_id")
        demo_panoramas.exclude(pk__in=used_panoramas).delete()
        demo_panoramas.update(is_public=False)

        if (
            building.panoramas.using(db).exists()
            or building.facades.using(db).exists()
            or Placement.objects.using(db).filter(building=building).exists()
            or building.designs.using(db).exclude(author__username="Muralium Studio", title="Волжский ветер").exists()
        ):
            continue
        building.delete(using=db)


class Migration(migrations.Migration):
    dependencies = [
        ("placements", "0008_moderationdecision_deletion_reason_and_more"),
        ("buildings", "0003_panorama_facadephoto_panorama"),
    ]

    operations = [migrations.RunPython(remove_estate_demo, migrations.RunPython.noop)]
