from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import User
from apps.avia_brand.models import BrandSource
from apps.avia_brand.services import REPOSITORIES
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.workspaces.models import Workspace


class Command(BaseCommand):
    help = "Attach the three AVIA sources to an existing owner's organization; no private content copied."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)

    @transaction.atomic
    def handle(self, *args, **options):
        user = User.objects.filter(email=options["email"]).first()
        membership = OrgMembership.objects.filter(user=user, org_role="owner").first()
        if not membership:
            raise CommandError("Create the owner with createsuperuser first")
        for repo, name in REPOSITORIES.items():
            source = BrandSource.objects.filter(repository=repo).first()
            if source and source.workspace.organization_id != membership.organization_id:
                raise CommandError("Source already belongs to another organization")
            if not source:
                ws = Workspace.objects.create(
                    organization=membership.organization,
                    name=name,
                    timezone="America/Santiago",
                    approval_workflow_mode="required_internal",
                )
                source = BrandSource.objects.create(workspace=ws, repository=repo)
            WorkspaceMembership.objects.get_or_create(
                user=user, workspace=source.workspace, defaults={"workspace_role": "owner"}
            )
        self.stdout.write("Three brand sources configured; no identities downloaded.")
