from typing import List, Dict, Any
import json
from openai import OpenAI
from app.config import settings
import logging
import httpx
from openai import OpenAI

logger = logging.getLogger(__name__)

# Prompt atualizado para nomes intuitivos em português
ONTOLOGY_PROMPT = """
Analise o seguinte texto e identifique o melhor esquema de Ontologia (Entidades e Relacionamentos). 
O objetivo é criar um Grafo de Conhecimento que seja claro para pessoas leigas, usando termos em PORTUGUÊS.

1. ENTIDADES (máx 50 - seja abrangente):
   - PESSOA: Nomes completos, autores, pesquisadores.
   - ORGANIZAÇÃO: Instituições, empresas, grupos.
   - CONCEITO: Doenças, tratamentos, teorias, ideias abstratas.
   - TERMO_TÉCNICO: Termos específicos, moléculas, leis, componentes.
   - LOCAL: Países, cidades, endereços físicos.
   - EVENTO/DATA: Reuniões, marcos históricos, períodos.
   - ADAPTE: Crie tipos novos se o domínio exigir (ex: "PROTEÍNA", "PROJETO_DE_LEI").

2. RELACIONAMENTOS (máx 100 - use verbos intuitivos em PORTUGUÊS):
   - Use nomes como: "pertence_a", "causa", "trabalha_em", "localizado_em", "menciona", "colabora_com", "trata_de".
   - Evita nomes excessivamente técnicos se houver uma alternativa simples.

FORMATO: Apenas JSON.
{
  "entities": [
    {"name": "NomeDoTipo", "description": "Breve descrição em português"}
  ],
  "relations": [
    {"label": "NOME_DO_RELACIONAMENTO", "source": "NomeDoTipo", "target": "NomeDoTipo", "description": "..."}
  ]
}
"""

class OntologyBuilder:
    def __init__(self):
        try:
            # Check if we should verify SSL
            verify = settings.VERIFY_SSL
            logger.info(f"Initializing OpenAI client with VERIFY_SSL={verify}")
            
            # Pre-initialize httpx client to catch/avoid hangs
            self.http_client = httpx.Client(verify=verify)
            
            self.client = OpenAI(
                api_key=settings.OPENAI_API_KEY,
                base_url=settings.LLM_BASE_URL,
                http_client=self.http_client
            )
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI client in OntologyBuilder: {e}")
            # If it failed and we were trying to verify, try one last time without verification
            if settings.VERIFY_SSL:
                try:
                    logger.warning("Attempting fallback with verify=False...")
                    self.http_client = httpx.Client(verify=False)
                    self.client = OpenAI(
                        api_key=settings.OPENAI_API_KEY,
                        base_url=settings.LLM_BASE_URL,
                        http_client=self.http_client
                    )
                except Exception as e2:
                    logger.error(f"Critical fallback failed: {e2}")
                    raise
            else:
                raise

        self.model = settings.OPENAI_MODEL

    def build(self, chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Builds an ontology by analyzing a representative sample of chunks.
        """
        # Select representative chunks (e.g., first few and some from middle)
        sample_size = min(5, len(chunks))
        sample_text = "\n---\n".join([c["text"][:2000] for c in chunks[:sample_size]])
        
        logger.info(f"Generating ontology using {self.model} via Direct OpenAI...")
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": ONTOLOGY_PROMPT},
                    {"role": "user", "content": sample_text}
                ],
                temperature=0.1
            )
            
            raw_content = response.choices[0].message.content or ""
            ontology = self._parse_json(raw_content)
            usage = response.usage.model_dump() if hasattr(response, 'usage') else {}

            logger.info(f"Discovered {len(ontology.get('entities', []))} entities and {len(ontology.get('relations', []))} relations.")
            return {
                "ontology": ontology,
                "usage": usage
            }
            
        except Exception as e:
            logger.error(f"Ontology generation failed: {e}")
            return {"ontology": {"entities": [], "relations": []}, "usage": {}, "error": str(e)}

    def _parse_json(self, text: str) -> Dict[str, Any]:
        """
        Robustly parses JSON from text, handling potential markdown wrappers.
        """
        text = text.strip()
        if not text:
            logger.error("LLM returned empty response content.")
            return {"entities": [], "relations": []}

        # Try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try to extract from markdown code blocks
        import re
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Last resort: find first { and last }
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1:
            try:
                return json.loads(text[start:end+1])
            except json.JSONDecodeError:
                pass

        logger.error(f"Failed to parse JSON from response: {text[:500]}...")
        return {"ontology": {"entities": [], "relations": []}, "usage": {}}
