from django.apps import AppConfig


class EventShopAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "eventshop_app"
    verbose_name = "Event shop"
    dpy_package = "eventshop_app.package"
