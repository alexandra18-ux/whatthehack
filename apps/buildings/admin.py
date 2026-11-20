from django.contrib import admin

from .models import Building, FacadePhoto

admin.site.register(Building)


@admin.register(FacadePhoto)
class FacadePhotoAdmin(admin.ModelAdmin):
    exclude = ("panorama",)
