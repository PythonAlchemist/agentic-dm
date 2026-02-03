"""Text-to-Speech service for NPC voice synthesis.

This module provides an abstraction layer for TTS providers,
allowing NPCs to speak in Discord voice channels.

Currently a stub implementation - providers like ElevenLabs
can be integrated in the future.
"""

import logging
from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class TTSProvider(str, Enum):
    """Supported TTS providers."""

    ELEVENLABS = "elevenlabs"
    GOOGLE = "google"
    AZURE = "azure"
    LOCAL = "local"
    STUB = "stub"


class VoiceProfile(BaseModel):
    """Voice profile for an NPC.

    Defines the voice characteristics for TTS synthesis.
    """

    provider: TTSProvider = TTSProvider.STUB
    voice_id: Optional[str] = None
    voice_name: Optional[str] = None

    # Voice characteristics (provider-dependent)
    stability: float = Field(default=0.5, ge=0, le=1)
    similarity_boost: float = Field(default=0.75, ge=0, le=1)
    style: float = Field(default=0.0, ge=0, le=1)
    use_speaker_boost: bool = True

    # Voice modifiers
    pitch_shift: float = Field(default=0.0, ge=-1, le=1)
    speed: float = Field(default=1.0, ge=0.5, le=2.0)


class TTSResult(BaseModel):
    """Result of TTS synthesis."""

    success: bool
    audio_data: Optional[bytes] = None
    audio_format: str = "mp3"
    duration_ms: Optional[int] = None
    error: Optional[str] = None


class BaseTTSProvider(ABC):
    """Abstract base class for TTS providers."""

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        voice_profile: VoiceProfile,
    ) -> TTSResult:
        """Synthesize speech from text.

        Args:
            text: Text to convert to speech.
            voice_profile: Voice configuration.

        Returns:
            TTSResult with audio data or error.
        """
        pass

    @abstractmethod
    async def get_available_voices(self) -> list[dict]:
        """Get list of available voices.

        Returns:
            List of voice info dictionaries.
        """
        pass


class StubTTSProvider(BaseTTSProvider):
    """Stub TTS provider for development/testing."""

    async def synthesize(
        self,
        text: str,
        voice_profile: VoiceProfile,
    ) -> TTSResult:
        """Stub implementation - returns empty audio."""
        logger.info(f"[STUB TTS] Would synthesize: {text[:50]}...")
        return TTSResult(
            success=True,
            audio_data=None,
            error="Stub provider - no audio generated",
        )

    async def get_available_voices(self) -> list[dict]:
        """Return stub voices."""
        return [
            {"id": "stub_male_1", "name": "Stub Male Voice", "gender": "male"},
            {"id": "stub_female_1", "name": "Stub Female Voice", "gender": "female"},
        ]


class ElevenLabsProvider(BaseTTSProvider):
    """ElevenLabs TTS provider (stub - requires API key).

    To use:
    1. Get API key from elevenlabs.io
    2. Set ELEVENLABS_API_KEY environment variable
    3. Install elevenlabs package
    """

    def __init__(self, api_key: Optional[str] = None):
        """Initialize ElevenLabs provider.

        Args:
            api_key: ElevenLabs API key.
        """
        self.api_key = api_key
        self._client = None

    async def synthesize(
        self,
        text: str,
        voice_profile: VoiceProfile,
    ) -> TTSResult:
        """Synthesize speech using ElevenLabs.

        Note: Requires elevenlabs package and API key.
        """
        if not self.api_key:
            return TTSResult(
                success=False,
                error="ElevenLabs API key not configured",
            )

        # TODO: Implement actual ElevenLabs integration
        # from elevenlabs import VoiceSettings, generate
        #
        # audio = generate(
        #     text=text,
        #     voice=voice_profile.voice_id,
        #     model="eleven_multilingual_v2",
        #     voice_settings=VoiceSettings(
        #         stability=voice_profile.stability,
        #         similarity_boost=voice_profile.similarity_boost,
        #         style=voice_profile.style,
        #         use_speaker_boost=voice_profile.use_speaker_boost,
        #     ),
        # )

        logger.warning("ElevenLabs integration not fully implemented")
        return TTSResult(
            success=False,
            error="ElevenLabs integration not implemented",
        )

    async def get_available_voices(self) -> list[dict]:
        """Get available ElevenLabs voices."""
        if not self.api_key:
            return []

        # TODO: Implement voice listing
        return []


class TTSService:
    """Main TTS service for NPC voice synthesis.

    Manages TTS providers and voice profiles.
    """

    def __init__(self):
        """Initialize the TTS service."""
        self._providers: dict[TTSProvider, BaseTTSProvider] = {
            TTSProvider.STUB: StubTTSProvider(),
        }
        self._default_provider = TTSProvider.STUB

    def register_provider(
        self,
        provider_type: TTSProvider,
        provider: BaseTTSProvider,
    ) -> None:
        """Register a TTS provider.

        Args:
            provider_type: The provider type.
            provider: The provider instance.
        """
        self._providers[provider_type] = provider

    def set_default_provider(self, provider_type: TTSProvider) -> None:
        """Set the default TTS provider.

        Args:
            provider_type: The provider to use as default.
        """
        if provider_type not in self._providers:
            raise ValueError(f"Provider {provider_type} not registered")
        self._default_provider = provider_type

    async def synthesize(
        self,
        text: str,
        voice_profile: Optional[VoiceProfile] = None,
    ) -> TTSResult:
        """Synthesize speech from text.

        Args:
            text: Text to convert to speech.
            voice_profile: Optional voice configuration.

        Returns:
            TTSResult with audio data or error.
        """
        if voice_profile is None:
            voice_profile = VoiceProfile()

        provider = self._providers.get(voice_profile.provider)
        if not provider:
            provider = self._providers.get(self._default_provider)

        if not provider:
            return TTSResult(
                success=False,
                error="No TTS provider available",
            )

        return await provider.synthesize(text, voice_profile)

    async def get_available_voices(
        self,
        provider_type: Optional[TTSProvider] = None,
    ) -> list[dict]:
        """Get available voices.

        Args:
            provider_type: Optional specific provider.

        Returns:
            List of voice info dictionaries.
        """
        provider = self._providers.get(
            provider_type or self._default_provider
        )
        if not provider:
            return []

        return await provider.get_available_voices()

    def configure_elevenlabs(self, api_key: str) -> None:
        """Configure ElevenLabs provider.

        Args:
            api_key: ElevenLabs API key.
        """
        self._providers[TTSProvider.ELEVENLABS] = ElevenLabsProvider(api_key)
        logger.info("ElevenLabs provider configured")


# Global singleton
_tts_service: Optional[TTSService] = None


def get_tts_service() -> TTSService:
    """Get the global TTS service instance."""
    global _tts_service
    if _tts_service is None:
        _tts_service = TTSService()
    return _tts_service
