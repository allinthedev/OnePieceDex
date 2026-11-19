from django.apps import AppConfig


class RoyaleAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "royale_app"
    verbose_name = "Grand Line Royale"
    dpy_package = "royale_app.package"
