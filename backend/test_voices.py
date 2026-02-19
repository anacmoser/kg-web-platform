import os
import io
import base64
import soundfile as sf
from app.api.local_audio import local_audio

test_text = "Ola, meu nome e Nadia e eu falo portugues brasileiro."

voices_to_test = ['pf_dora', 'af_heart', 'af_sky', 'af_sarah', 'af_bella']

print("Testing different voices for Portuguese...")
print("=" * 60)

for voice in voices_to_test:
    try:
        print(f"\nTesting voice: {voice}")
        audio = local_audio.generate_audio_base64(test_text, voice=voice, speed=1.0)
        
        if audio:
            data = base64.b64decode(audio)
            filename = f'test_pt_{voice}.wav'
            with open(filename, 'wb') as f:
                f.write(data)
            print(f'  OK Generated: {filename} ({len(data)} bytes)')
        else:
            print(f'  FAIL to generate audio')
    except Exception as e:
        print(f'  ERROR: {e}')

print("\n" + "=" * 60)
print("Listen to the files and choose the best sounding voice!")
