import uuid

from django.db import migrations, models


def populate_membership_public_ids(apps, schema_editor):
    LobbyMembership = apps.get_model("lobbies", "LobbyMembership")
    for membership in LobbyMembership.objects.filter(public_id__isnull=True):
        membership.public_id = uuid.uuid4()
        membership.save(update_fields=["public_id"])


class Migration(migrations.Migration):

    dependencies = [
        ("lobbies", "0003_lobbyauditevent_lobbyban"),
    ]

    operations = [
        migrations.AddField(
            model_name="lobbymembership",
            name="public_id",
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.RunPython(populate_membership_public_ids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="lobbymembership",
            name="public_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
