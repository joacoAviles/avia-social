from django.apps import AppConfig


class AviaBrandConfig(AppConfig):
    name = "apps.avia_brand"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from django.db.models.signals import post_migrate

        post_migrate.connect(self.register_tasks, sender=self)

    @staticmethod
    def register_tasks(sender, **kwargs):
        from apps.common.background import register_recurring_task

        from .tasks import sync_google_calendars

        register_recurring_task(sync_google_calendars, repeat=120, verbose_name="avia_google_calendars")
