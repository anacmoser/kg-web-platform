import os
import io
import base64
import soundfile as sf
from app.api.local_audio import local_audio

print("Testing Portuguese voice...")

# Test with pt-br
audio = local_audio.generate_audio_base64(
    "Olá, meu nome é Nadia e eu falo português brasileiro.", 
    voice='pf_dora', 
    speed=1.0
)

if audio:
    data = base64.b64decode(audio)
    print(f'Audio size: {len(data)} bytes')
    with open('test_pt_dora.wav', 'wb') as f:
        f.write(data)
    print('Saved to test_pt_dora.wav')
else:
    print('Failed to generate audio')
