from django.core.management.base import BaseCommand, CommandError

from apps.avia_brand.models import BrandSource
from apps.avia_brand.services import REPOSITORIES, SyncError, sync


class Command(BaseCommand):
    help = "Read GitHub and create pending revisions. Never approves or publishes."

    def add_arguments(self, parser):
        parser.add_argument("--repository", choices=list(REPOSITORIES))

    def handle(self, *args, **options):
        sources = BrandSource.objects.all()
        if options["repository"]:
            sources = sources.filter(repository=options["repository"])
        failures = 0
        for source in sources:
            try:
                revision = sync(source)
                self.stdout.write(f"{source.repository}: {revision.commit} ({revision.state})")
            except SyncError as exc:
                failures += 1
                self.stderr.write(f"{source.repository}: {exc}")
        if failures:
            raise CommandError(f"{failures} source(s) failed; rerun safely after correcting access")
