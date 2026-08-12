from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    verbose_name = "Comptes"

    def ready(self):
        # Registers the OpenAPI security scheme for our JWT auth subclass.
        from apps.accounts import schema  # noqa: F401
