from django.apps import AppConfig


class HuntAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "hunt_app"
    verbose_name = "Treasure hunts"
    dpy_package = "hunt_app.package"
