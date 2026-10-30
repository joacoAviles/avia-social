import logging

from background_task import background

from .models import CalendarConnection

logger = logging.getLogger(__name__)


@background(schedule=0)
def sync_google_calendars():
    from .calendar_sync import sync_connection
    from .google_calendar import CalendarError

    for pk in CalendarConnection.objects.filter(managed=True).values_list("pk", flat=True):
        try:
            sync_connection(pk)
        except CalendarConnection.DoesNotExist:
            continue
        except CalendarError as exc:
            CalendarConnection.objects.filter(pk=pk).update(sync_error=str(exc)[:500])

        except Exception:
            logger.exception("Calendar synchronization failed for connection %s", pk)
            CalendarConnection.objects.filter(pk=pk).update(
                sync_error="No se pudo completar la sincronización. Revisa los registros de AVIA."
            )
