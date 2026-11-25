from django.apps import AppConfig


class SantaAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "santa_app"
    verbose_name = "Secret Santa"
    dpy_package = "santa_app.package"
