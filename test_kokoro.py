import os
import io
import base64
import soundfile as sf
from kokoro_onnx import Kokoro

print("--- Testando Kokoro-82M Local (Direto) ---")

model_path = "backend/kokoro-v0_19.onnx"
voices_path = "backend/voices.json"

if not os.path.exists(model_path):
    print(f"❌ Erro: Modelo não encontrado em {model_path}")
    exit(1)

try:
    kokoro = Kokoro(model_path, voices_path)
    text = "Olá! Eu sou a Nadia e agora estou falando totalmente de graça usando o seu computador local."
    samples, sample_rate = kokoro.create(text, voice="af_heart", speed=1.0, lang="en-us")
    
    buffer = io.BytesIO()
    sf.write(buffer, samples, sample_rate, format='WAV')
    audio_b64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
    
    print(f"✅ Sucesso! Áudio gerado ({len(audio_b64)} bytes).")
    with open("kokoro_test.wav", "wb") as f:
        f.write(base64.b64decode(audio_b64))
    print("Arquivo 'kokoro_test.wav' criado.")
except Exception as e:
    print(f"❌ Erro na geração: {e}")
