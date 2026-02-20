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
            verify = settings.VERIFY_SSL
            logger.info(f"Initializing KGExtractor with VERIFY_SSL={verify}")
            self.http_client = httpx.Client(verify=verify)
            self.client = OpenAI(
                api_key=settings.OPENAI_API_KEY,
                base_url=settings.LLM_BASE_URL,
                http_client=self.http_client
            )
        except Exception as e:
            logger.error(f"Failed to initialize KGExtractor: {e}")
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

    def _build_prompt(self, chunk: Dict[str, Any], ontology: Dict[str, Any], user_instructions: str) -> str:
        entities_str = "\n".join(
            [f"  - {e['name']}: {e.get('description', '')}" for e in ontology.get("entities", [])]
        )
        relations_str = "\n".join(
            [f"  - {r['label']}: ({r['source']}) --> ({r['target']}) | {r.get('description', '')}"
             for r in ontology.get("relations", [])]
        )

        user_context_block = (
            f"\n*** INSTRUÇÕES EXPLÍCITAS DO USUÁRIO (Rigor Máximo) ***\n{user_instructions}\n"
            if user_instructions else ""
        )

        return f"""Você é um arquiteto sênior de grafos especializados em extração TÉCNICA e METODOLÓGICA.
{user_context_block}

OBJETIVO: Extrair triplas que representam a lógica, matemática e os processos descritos no texto.

CADEIA DE ATENÇÃO (Respeite rigorosamente):
1. ANÁLISE TÉCNICA: Identifique fórmulas, métodos estatísticos, fontes de dados e passos procedimentais. 
2. FILTRO DE RELEVÂNCIA: Ignore exemplos triviais (ex: tipos de comida, nomes de arquivos, anos genéricos) SE eles não forem o foco da instrução do usuário. 
   - Se o texto diz "Cálculo do PIB do Repolho", a entidade importante é "REPOLHO" como "PRODUTO" ou "VARIAVEL", não como um "SETOR ECONÔMICO" solto.
3. PADRONIZAÇÃO: Unifique nomes imediatamente. "Secretaria" -> "Secretaria da Fazenda". "Sigla" -> "Nome Completo".
4. VERIFICAÇÃO DE INSTRUÇÃO: Se o usuário disse "FOQUE EM METODOLOGIA", 80% das suas triplas devem ser sobre métodos, fluxos e indicadores.

ESQUEMA PERMITIDO:
ENTIDADES: {entities_str}
RELAÇÕES: {relations_str}

REGRAS FINAIS:
- Proibido triplas genéricas (A está_relacionado_a B).
- Proibido source == target.
- Use nomes canônicos e técnicos.

TEXTO:
{chunk["text"]}

RETORNE APENAS JSON:
{{
  "chain_of_thought": "Passo 1: Identifiquei o método X. Passo 2: Verifiquei que 'tomate' é apenas um parâmetro da equação Y. Passo 3: Segui a regra de ignorar locais.",
  "triples": [
    {{"source": "Nome Técnico", "source_type": "TIPO", "target": "Nome Técnico", "target_type": "TIPO", "relation": "verbo_infinitivo"}}
  ]
}}
"""

    def extract_triples(
        self,
        chunk: Dict[str, Any],
        ontology: Dict[str, Any],
        user_instructions: str = ""
    ) -> Dict[str, Any]:
        """
        Extracts semantic triples from a chunk, with strict post-processing validation.
        """
        prompt = self._build_prompt(chunk, ontology, user_instructions)
        valid_types = {e["name"].upper() for e in ontology.get("entities", [])}

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Você é um extrator preciso de Grafos de Conhecimento. "
                            "Retorne SEMPRE e APENAS uma lista JSON válida. Nenhum texto antes ou depois. "
                            "Se não houver nada para extrair, retorne []."
                        )
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0
            )

            raw_content = response.choices[0].message.content or ""
            usage = response.usage.model_dump() if hasattr(response, 'usage') else {}
            content = self._parse_json(raw_content)

            # Normalize to list
            raw_triples: List[Dict] = []
            if isinstance(content, list):
                raw_triples = content
            elif isinstance(content, dict):
                for key in ("triples", "result", "data"):
                    if key in content and isinstance(content[key], list):
                        raw_triples = content[key]
                        break
                if not raw_triples:
                    for val in content.values():
                        if isinstance(val, list):
                            raw_triples = val
                            break

            # Strict validation
            validated = self._validate_triples(raw_triples, valid_types)

            logger.info(
                f"Chunk {chunk.get('index', '?')}: "
                f"{len(raw_triples)} raw → {len(validated)} valid triples"
            )
            return {"triples": validated, "usage": usage}

        except Exception as e:
            logger.error(f"KG extraction failed for chunk {chunk.get('index')}: {e}")
            raise

    def _validate_triples(
        self, triples: List[Dict], valid_types: set
    ) -> List[Dict[str, Any]]:
        """
        Post-processing filter with strict quality rules:
        - All required keys must be present and non-empty
        - source_type and target_type must be in the known ontology schema
        - source != target (no self-loops)
        - No trivially bad entities (pure numbers, single chars, file paths)
        - Deduplicate (source, target, relation) tuples
        """
        BANNED_PATTERNS = {
            # Single words that are meaningless as entities
            "dados", "informação", "texto", "arquivo", "documento",
            "conteúdo", "resultado", "valor", "item", "elemento",
        }
        VAGUE_RELATIONS = {
            "está_relacionado_a", "é_associado_com", "relaciona_se",
            "tem_relação", "possui_relação", "faz_parte", "integra",
        }

        seen = set()
        validated = []

        for t in triples:
            if not isinstance(t, dict):
                continue

            source = str(t.get("source", "")).strip()
            target = str(t.get("target", "")).strip()
            relation = str(t.get("relation", "")).strip().lower().replace(" ", "_")
            source_type = str(t.get("source_type", "")).strip().upper()
            target_type = str(t.get("target_type", "")).strip().upper()

            # Required fields check
            if not source or not target or not relation:
                continue

            # Self-loop check
            if source.lower() == target.lower():
                continue

            # Entity quality check: no pure numbers, too short, or banned words
            if self._is_bad_entity(source, BANNED_PATTERNS):
                logger.debug(f"Rejected entity (source): '{source}'")
                continue
            if self._is_bad_entity(target, BANNED_PATTERNS):
                logger.debug(f"Rejected entity (target): '{target}'")
                continue

            # Vague relation check
            if relation in VAGUE_RELATIONS:
                logger.debug(f"Rejected vague relation: '{relation}'")
                continue

            # Type validation (only if ontology has types defined)
            if valid_types:
                if source_type not in valid_types:
                    # Attempt to find a close match, otherwise use UNKNOWN
                    source_type = "DESCONHECIDO"
                if target_type not in valid_types:
                    target_type = "DESCONHECIDO"

            # Deduplication
            triple_key = (source.lower(), target.lower(), relation)
            if triple_key in seen:
                continue
            seen.add(triple_key)

            validated.append({
                "source": source,
                "source_type": source_type,
                "target": target,
                "target_type": target_type,
                "relation": relation
            })

        return validated

    @staticmethod
    def _is_bad_entity(name: str, banned: set) -> bool:
        """Returns True if entity name is noise (should be rejected)."""
        # Pure numbers are noise (years, IDs)
        if name.isdigit():
            return True
        # Very short names (1-2 chars)
        if len(name) <= 2:
            return True
        # File path patterns
        if '/' in name or '\\' in name or name.endswith(('.pdf', '.csv', '.docx', '.txt')):
            return True
        # Banned generic words (case-insensitive, single word check)
        if name.lower().strip() in banned:
            return True
        return False

    def _parse_json(self, text: str) -> Any:
        """Robustly parses JSON from LLM text output."""
        text = text.strip()
        if not text:
            logger.error("LLM returned empty response.")
            return []

        # Direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Strip markdown code fences
        import re
        json_match = re.search(r'```(?:json)?\s*([\[\{].*?[\]\}])\s*```', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Last resort: extract outermost [ ] or { }
        start_candidates = [idx for idx in [text.find('['), text.find('{')] if idx != -1]
        end_candidates = [idx for idx in [text.rfind(']'), text.rfind('}')] if idx != -1]

        start_idx = min(start_candidates) if start_candidates else None
        end_idx = max(end_candidates) if end_candidates else None

        if start_idx is not None and end_idx is not None and end_idx > start_idx:
            try:
                return json.loads(text[start_idx:end_idx + 1])
            except json.JSONDecodeError:
                pass

        logger.error(f"Failed to parse JSON from response: {text[:300]}...")
        return []
