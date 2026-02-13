from typing import List, Dict, Any
import json
from openai import OpenAI
from app.config import settings
import logging

import httpx

logger = logging.getLogger(__name__)

class KGExtractor:
    def __init__(self):
        try:
            # Check if we should verify SSL
            verify = settings.VERIFY_SSL
            logger.info(f"Initializing OpenAI client in KGExtractor with VERIFY_SSL={verify}")
            
            # Pre-initialize httpx client
            self.http_client = httpx.Client(verify=verify)
            
            self.client = OpenAI(
                api_key=settings.OPENAI_API_KEY,
                base_url=settings.LLM_BASE_URL,
                http_client=self.http_client
            )
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI client in KGExtractor: {e}")
            # Fallback if verify=True failed
            if settings.VERIFY_SSL:
                try:
                    logger.warning("Attempting fallback with verify=False in KGExtractor...")
                    self.http_client = httpx.Client(verify=False)
                    self.client = OpenAI(
                        api_key=settings.OPENAI_API_KEY,
                        base_url=settings.LLM_BASE_URL,
                        http_client=self.http_client
                    )
                except Exception as e2:
                    logger.error(f"Critical fallback failed in KGExtractor: {e2}")
                    raise
            else:
                raise

        self.model = settings.OPENAI_MODEL

    def extract_triples(self, chunk: Dict[str, Any], ontology: Dict[str, Any], user_instructions: str = "") -> List[Dict[str, Any]]:
        """
        Extracts triples from a chunk based on the provided ontology and user context.
        """
        # Prepare context from ontology
        entities_str = ", ".join([e["name"] for e in ontology.get("entities", [])])
        relations_str = ", ".join([r["label"] for r in ontology.get("relations", [])])
        
        user_context_block = f"\nINSTRUÇÕES ADICIONAIS DO USUÁRIO:\n{user_instructions}\n" if user_instructions else ""

        prompt = f"""
        VOCÊ É UM ANALISTA FORENSE E ESPECIALISTA EM GRAFOS DE CONHECIMENTO DE CLASSE MUNDIAL.
        Sua tarefa é extrair triplas semânticas ricas e PROFISSIONAIS do texto abaixo.
        {user_context_block}
        
        ESQUEMA DE ENTIDADES PERMITIDAS: {entities_str}
        ESQUEMA DE RELAÇÕES PERMITIDAS: {relations_str}

        DIRETRIZES DE EXTRAÇÃO PROFISSIONAL:
        1. **Filtro de Ruído (CRÍTICO)**: 
           - NÃO extraia entidades sem nexo ou inúteis (ex: nomes de diretórios, caminhos de arquivo, extensões como .pdf).
           - NÃO crie entidades para ANOS isolados (ex: "2023", "2024") a menos que sejam o SUJEITO central de uma métrica.
           - Evite entidades genéricas como "Banco de Dados" se estiverem apenas descrevendo a infraestrutura técnica irrelevante para o negócio.
        2. **Hierarquia de Texto**: Identifique títulos (#, ##) e crie relações de "pertence_à_seção" para manter o contexto estrutural.
        3. **Nexo Semântico**: Cada tripla deve representar um fato de negócio ou técnico real. Conecte as entidades para que o grafo conte a "história" do documento.
        4. **Análise de Tabelas**: Extraia dados de tabelas markdown com precisão absoluta.
        
        TEXTO PARA ANÁLISE (PARTE DO DOCUMENTO):
        {chunk["text"]}

        FORMATO DE SAÍDA (LISTA JSON):
        [
            {{"source": "Nome da Entidade", "source_type": "TIPO", "target": "Nome da Entidade", "target_type": "TIPO", "relation": "RELAÇÃO"}}
        ]

        REGRAS DE OURO:
        - Retorne APENAS o JSON.
        - Se o texto citar uma metodologia, extraia as etapas como uma sequência.
        - Use português técnico e PRECISÃO SEMÂNTICA.
        """
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "Você é um extrator preciso de Grafos de Conhecimento. Extraia triplas (sujeito, relação, objeto) em PORTUGUÊS, usando o esquema de ontologia fornecido."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0
            )
            
            raw_content = response.choices[0].message.content or ""
            content = self._parse_json(raw_content)
            usage = response.usage.model_dump() if hasattr(response, 'usage') else {}
            
            # Handle variations in JSON structure
            triples = []
            if isinstance(content, list):
                triples = content
            elif isinstance(content, dict):
                if "triples" in content:
                    triples = content["triples"]
                elif "result" in content:
                    triples = content["result"]
                else:
                    # Try to find the first list value
                    for val in content.values():
                        if isinstance(val, list):
                            triples = val
                            break
            
            # Ensure each triple has expected keys
            validated_triples = []
            for t in triples:
                if isinstance(t, dict) and all(k in t for k in ["source", "target", "relation"]):
                    validated_triples.append(t)
            
            return {
                "triples": validated_triples,
                "usage": usage
            }
                
        except Exception as e:
            logger.error(f"KG extraction failed for chunk {chunk.get('index')}: {e}")
            raise e

    def _parse_json(self, text: str) -> Any:
        """
        Robustly parses JSON from text, handling potential markdown wrappers.
        """
        text = text.strip()
        if not text:
            logger.error("LLM returned empty response content.")
            return []

        # Try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try to extract from markdown code blocks
        import re
        # Check for list [ ] or object { }
        json_match = re.search(r'```(?:json)?\s*([\[\{].*?[\]\}])\s*```', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Last resort: find first [ or { and last ] or }
        start_idx = min([idx for idx in [text.find('['), text.find('{')] if idx != -1] or [None])
        end_idx = max([idx for idx in [text.rfind(']'), text.rfind('}')] if idx != -1] or [None])
        
        if start_idx is not None and end_idx is not None:
            try:
                return json.loads(text[start_idx:end_idx+1])
            except json.JSONDecodeError:
                pass

        logger.error(f"Failed to parse JSON from response: {text[:500]}...")
        return {"triples": [], "usage": {}}
