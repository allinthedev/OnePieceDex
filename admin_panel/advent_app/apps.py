from django.apps import AppConfig


class AdventAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "advent_app"
    verbose_name = "Advent calendar"
    dpy_package = "advent_app.package"
