from django.apps import AppConfig


class SleighAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "sleigh_app"
    verbose_name = "Sleigh"
    dpy_package = "sleigh_app.package"
