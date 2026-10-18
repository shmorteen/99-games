"""Declare implemented Connect4 bot support without marking it playable."""

from django.db import migrations


def enable_connect4_bots(apps, schema_editor):
    GameDefinition = apps.get_model("games", "GameDefinition")
    GameDefinition.objects.filter(slug="connect4").update(supports_bots=True)


def disable_connect4_bots(apps, schema_editor):
    GameDefinition = apps.get_model("games", "GameDefinition")
    GameDefinition.objects.filter(slug="connect4").update(supports_bots=False)


class Migration(migrations.Migration):
    dependencies = [("games", "0002_gamedefinition")]

    operations = [migrations.RunPython(enable_connect4_bots, disable_connect4_bots)]
