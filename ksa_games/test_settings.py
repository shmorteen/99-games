"""Test settings for isolated local checks."""
from .channel_layers import build_in_memory_channel_layers_config
from .settings import *  # noqa: F403


CHANNEL_LAYERS = build_in_memory_channel_layers_config()
KSA_LOBBY_START_LOCK_BACKEND = "noop"
KSA_GAME_ACTION_LOCK_BACKEND = "noop"
KSA_CONNECT4_BOT_AUTOMATION_ENABLED = False
