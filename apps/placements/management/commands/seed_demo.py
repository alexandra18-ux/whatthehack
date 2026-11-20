import math

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files import File
from django.core.management.base import BaseCommand
from django.utils import timezone
from PIL import Image, ImageDraw

from apps.buildings.models import Building, FacadePhoto, Panorama
from apps.murals.models import MuralDesign
from apps.placements.models import Placement
from apps.placements.services.perspective import encode_image, render_placement

SAMPLES = [
    ("Волжский ветер", "Набережная · демонстрационная точка", "51.527800", "46.048800",
     ("#104c58", "#83c4ba", "#ff9a66", "#f4dba1"),
     "Волны и тёплый свет над Волгой. Эскиз повторяет изгибы реки."),
    ("Сад на стене", "Липки · демонстрационная точка", "51.529990", "46.035350",
     ("#303f2f", "#89a060", "#eec994", "#f88661"),
     "Городской сад с крупными листьями и цветами, заметными издалека."),
    ("Ритм города", "Астраханская · демонстрационная точка", "51.538350", "46.015780",
     ("#443673", "#aa8dde", "#fabb56", "#f37163"),
     "Цветные формы складываются в ритм городской архитектуры."),
]
CORNERS = [
    {"x": .323, "y": .206}, {"x": .864, "y": .305},
    {"x": .864, "y": .787}, {"x": .323, "y": .817},
]


def illustrated_facade(index):
    image = Image.new("RGB", (1200, 760), ["#c4d8d7", "#e0d6bc", "#bbcadb"][index])
    draw = ImageDraw.Draw(image)
    draw.ellipse((935, 46, 1075, 186), fill="#f5e4bb")
    draw.polygon([(0, 600), (1200, 560), (1200, 760), (0, 760)], fill="#a39a87")
    draw.polygon([(45, 243), (388, 114), (388, 656), (45, 600)], fill="#9e8c78")
    draw.polygon([(388, 114), (1087, 208), (1087, 607), (388, 656)], fill="#d9c1a4")
    draw.polygon([(34, 234), (388, 98), (1095, 194), (1095, 209), (388, 117), (34, 252)],
                 fill="#746a60")
    draw.polygon([(45, 569), (388, 628), (1087, 583), (1087, 610), (388, 661), (45, 601)],
                 fill="#756c61")
    for x in range(78, 350, 50):
        top = 270 - (x - 78) // 4
        for y in (top, top + 140):
            draw.polygon([(x, y), (x + 30, y - 8), (x + 30, y + 73), (x, y + 75)], fill="#4c5757")
            draw.line((x + 15, y, x + 15, y + 70), fill="#d4bb9f", width=3)
            draw.line((x, y + 32, x + 30, y + 28), fill="#d4bb9f", width=3)
    for y in range(170, 630, 19):
        draw.line((388, y, 1087, round(y + (222 - (y - 100) * .49) * .53)), fill="#cfb699", width=1)
    draw.polygon([(0, 705), (1200, 628), (1200, 656), (0, 748)], fill="#dfd3ba")
    draw.polygon([(1060, 642), (1170, 606), (1200, 614), (1116, 656)], fill="#81786b")
    draw.rectangle((1135, 380, 1144, 628), fill="#69594a")
    for x, y, radius in [(1110, 380, 63), (1168, 344, 58), (1175, 413, 72)]:
        draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill="#63765d")
    return image


def illustrated_design(index, colors):
    background, secondary, accent, light = colors
    image = Image.new("RGBA", (960, 620), background)
    draw = ImageDraw.Draw(image)
    if index == 0:
        draw.ellipse((605, 56, 822, 273), fill=accent)
        for offset, color in enumerate((light, secondary, "#367a79", "#183f57")):
            wave = [(x, int(225 + offset * 86 + 49 * math.sin(x / 121 + offset * .8)))
                    for x in range(0, 961, 8)]
            draw.polygon(wave + [(960, 620), (0, 620)], fill=color)
        for x, y in ((300, 144), (400, 116), (469, 162)):
            draw.line([(x-29, y+6), (x-11, y-4), (x, y+2), (x+10, y-5), (x+30, y-1)],
                      fill=light, width=4)
    elif index == 1:
        for x, color, lean in [(120, light, 140), (335, secondary, -105),
                               (590, light, 115), (802, secondary, -100)]:
            draw.line((x, 620, x + lean, 103), fill=color, width=9)
            for y in (180, 266, 352, 438, 524):
                stem = x + int(lean * (620 - y) / 517)
                draw.ellipse((stem - 87, y-24, stem + 4, y+29), fill=color)
                draw.ellipse((stem - 3, y-54, stem + 78, y+1), fill=color)
            draw.ellipse((x + lean - 37, 80, x + lean + 37, 154), fill=accent)
    else:
        draw.ellipse((-190, 46, 453, 689), fill=secondary)
        draw.polygon([(223, 620), (615, 0), (786, 0), (396, 620)], fill=accent)
        draw.polygon([(465, 620), (859, 0), (961, 0), (961, 255), (720, 620)], fill=light)
        draw.ellipse((514, 172, 735, 393), fill=background)
        draw.arc((33, 55, 450, 479), 90, 292, fill=light, width=18)
    return image


class Command(BaseCommand):
    help = "Создаёт вымышленные фасады, эскизы и опубликованные демопроекты."

    def handle(self, *args, **options):
        author, created = get_user_model().objects.get_or_create(username="Muralium Studio")
        if created:
            author.set_unusable_password()
            author.save(update_fields=["password"])

        for index, (title, address, latitude, longitude, colors, description) in enumerate(SAMPLES):
            building, _ = Building.objects.get_or_create(
                address=address, latitude=latitude, longitude=longitude,
            )
            if Placement.objects.filter(author=author, building=building, title=title).exists():
                continue

            facade_image = illustrated_facade(index)
            mural_image = illustrated_design(index, colors)

            facade = FacadePhoto(building=building, uploaded_by=author, is_public=True)
            facade.image = encode_image(facade_image, png=True)
            facade.save()

            design = MuralDesign(author=author, title=title, is_public=True)
            design.image = encode_image(mural_image, png=True)
            design.save()
            design.buildings.add(building)

            Placement.objects.create(
                author=author, building=building, facade_photo=facade, mural_design=design,
                title=title, description=description, corners=CORNERS, published_at=timezone.now(),
                status=Placement.Status.APPROVED,
                result_image=encode_image(render_placement(facade_image, mural_image, CORNERS), png=True),
            )

        building, _ = Building.objects.get_or_create(
            address="Усадьба Шмидта · улица Радищева, 14",
            defaults={"latitude": "51.525549", "longitude": "46.033877"},
        )
        sample_design = MuralDesign.objects.filter(author=author, is_public=True, title=SAMPLES[0][0]).first()
        if sample_design:
            sample_design.buildings.add(building)
        panorama = Panorama.objects.filter(building=building, title="Двор усадьбы Шмидта").first()
        if panorama is None:
            panorama = Panorama(
                building=building, title="Двор усадьбы Шмидта", initial_heading=-65,
                credit="FingerWiki", is_public=True,
                source_url="https://commons.wikimedia.org/wiki/File:Courtyard_of_the_P._P._Schmidt_Estate_in_Saratov,_21_September_2020.jpg",
                license_name="CC BY-SA 4.0", license_url="https://creativecommons.org/licenses/by-sa/4.0/",
            )
            source = settings.BASE_DIR / "static" / "panoramas" / "schmidt-courtyard.jpg"
            with source.open("rb") as image:
                panorama.image.save(source.name, File(image), save=False)
            panorama.save()

        self.stdout.write(self.style.SUCCESS("Демонстрационные проекты и панорама готовы."))
