import os
import logging
import base64
import numpy as np
import soundfile as sf
import io
import kokoro_onnx

logger = logging.getLogger(__name__)

class LocalAudioEngine:
    def __init__(self):
        self.kokoro = None
        self.model_path = os.path.join(os.path.dirname(__file__), "..", "..", "kokoro-v1.0.onnx")
        self.voices_path = os.path.join(os.path.dirname(__file__), "..", "..", "voices.bin")
        # Do not initialize on startup to prevent blocking imports

    def _ensure_initialized(self):
        if self.kokoro is not None:
            return True
            
        try:
            if os.path.exists(self.model_path) and os.path.exists(self.voices_path):
                logger.info(f"Initializing Kokoro from {self.model_path}")
                self.kokoro = kokoro_onnx.Kokoro(self.model_path, self.voices_path)
                logger.info("Kokoro-82M Local TTS Initialized.")
                return True
            else:
                logger.warning(f"Kokoro files not found at {self.model_path}. Local TTS disabled.")
                return False
        except Exception as e:
            logger.error(f"Failed to initialize Kokoro: {e}")
            self.kokoro = None
            return False

    def generate_audio_base64(self, text, voice="pf_dora", speed=1.0):
        if not self._ensure_initialized():
            logger.error("Kokoro engine not available.")
            return None
        
        try:
            # Generate audio (numpy array)
            audio, sample_rate = self.kokoro.create(
                text, 
                voice=voice, 
                speed=speed, 
                lang="pt-br"
            )
            
            # Convert numpy to WAV bytes in memory
            buffer = io.BytesIO()
            sf.write(buffer, audio, sample_rate, format='WAV')
            buffer.seek(0)
            
            return base64.b64encode(buffer.read()).decode('utf-8')
        except Exception as e:
            logger.error(f"Audio generation failed: {e}")
            return None

# Singleton instance
local_audio = LocalAudioEngine()
