from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import User
from apps.avia_brand.models import BrandSource
from apps.avia_brand.services import SOURCES
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.workspaces.models import Workspace


class Command(BaseCommand):
    help = (
        "Attach the AVIA brands (one folder each in Avia-Brands) to an owner's organization; no private content copied."
    )

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)

    @transaction.atomic
    def handle(self, *args, **options):
        user = User.objects.filter(email=options["email"]).first()
        membership = OrgMembership.objects.filter(user=user, org_role="owner").first()
        if not membership:
            raise CommandError("Create the owner with createsuperuser first")
        for (repo, path), name in SOURCES.items():
            source = BrandSource.objects.filter(repository__iexact=repo, path=path).first()
            if source and source.workspace.organization_id != membership.organization_id:
                raise CommandError("Source already belongs to another organization")
            if not source:
                ws = Workspace.objects.create(
                    organization=membership.organization,
                    name=name,
                    timezone="America/Santiago",
                    approval_workflow_mode="required_internal",
                )
                source = BrandSource.objects.create(workspace=ws, repository=repo, path=path)
            WorkspaceMembership.objects.get_or_create(
                user=user, workspace=source.workspace, defaults={"workspace_role": "owner"}
            )
        self.stdout.write(f"{len(SOURCES)} brand sources configured; no identities downloaded.")
