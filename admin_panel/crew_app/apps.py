from django.apps import AppConfig


class CrewAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "crew_app"
    verbose_name = "Crews"
    dpy_package = "crew_app.package"
