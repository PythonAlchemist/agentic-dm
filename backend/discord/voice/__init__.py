"""Voice synthesis package for NPC Discord integration.

This package provides TTS (Text-to-Speech) capabilities for NPCs
to speak in Discord voice channels.

Currently a stub - full implementation planned for future.
"""

from backend.discord.voice.tts_service import (
    TTSProvider,
    VoiceProfile,
    TTSService,
    get_tts_service,
)

__all__ = [
    "TTSProvider",
    "VoiceProfile",
    "TTSService",
    "get_tts_service",
]
