from urllib.parse import urlsplit
from django.conf import settings
from django.db import migrations


def identify_site(apps, schema_editor):
    Site = apps.get_model("sites", "Site")
    for site in Site.objects.filter(name__in=["Brightbean", "BrightBean", "BrightBean Studio"]):
        site.name = "AVIA Social"
        if site.domain == "studio.brightbean.xyz":
            site.domain = urlsplit(settings.APP_URL).netloc or "localhost"
        site.save(update_fields=["name", "domain"])


class Migration(migrations.Migration):
    dependencies = [("avia_brand", "0001_initial"), ("sites", "0002_alter_domain_unique"), ("accounts", "0004_set_site_brightbean")]
    operations = [migrations.RunPython(identify_site, migrations.RunPython.noop)]
