from django.apps import AppConfig


class ApiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "cosapweb.api"

    def ready(self) -> None:
        import cosapweb.api.signals
