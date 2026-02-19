import httpx
from openai import OpenAI
import os
from dotenv import load_dotenv

# Carrega variáveis do .env do backend
load_dotenv('backend/.env')

api_key = os.getenv('OPENAI_API_KEY')
base_url = os.getenv('LLM_BASE_URL')

client = OpenAI(
    api_key=api_key,
    base_url=base_url,
    http_client=httpx.Client(verify=False) # Ignora SSL se necessário para o teste
)

print("--- Verificando Acesso a Modelos de Áudio ---")
try:
    models = client.models.list()
    model_ids = [m.id for m in models.data]
    
    targets = ["gpt-4o-audio-preview", "gpt-4o-mini-audio-preview"]
    found = False
    
    for target in targets:
        if target in model_ids:
            print(f"AVAILABLE: {target}")
            found = True
        else:
            print(f"NOT FOUND: {target}")
            
    if not found:
        print("\nO seu projeto ainda não tem acesso aos modelos de áudio nativo.")
        print("Geralmente, isso requer estar no 'Usage Tier 3' ou superior da OpenAI.")
    else:
        print("\nSeu projeto tem os modelos! Se o erro 403 persistir, verifique as permissões da sua API Key.")

except Exception as e:
    print(f"Erro ao listar modelos: {e}")
