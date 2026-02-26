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

        return f"""Você é um arquiteto sênior de grafos especializados em extração SEMÂNTICA, TÉCNICA e ESTRUTURAL.
{user_context_block}

OBJETIVO: Extrair triplas que representam a essência, a lógica, os processos e o CONTEXTO (Épocas, Marcos, Estruturas) do texto, considerando as informações como parte de um todo.

CADEIA DE ATENÇÃO (Respeite rigorosamente):
1. ANÁLISE INTEGRAL: Identifique não apenas métodos, mas os PILARES do texto. Se o texto for sobre História, datas, períodos ou pessoas SÃO fundamentais, mesmo que sejam números ou nomes. Caso contrário, evite extrair números soltos que não tenham peso semântico. Analise o contexto de forma holística.
2. FILTRO DE RELEVÂNCIA: Ignore ruído (nomes de arquivos estáticos, textos incompletos de formatação), mas NUNCA ignore marcos temporais ou espaciais que definem o assunto.
3. PADRONIZAÇÃO & DESDUPLICAÇÃO: Unifique entidades que são a mesma coisa. "Secretaria" -> "Secretaria da Fazenda". Nunca crie entidades duplicadas sob sinônimos. Extraia o nome mais formal.
4. EXAUSTIVIDADE & DESCRIÇÃO: Toda entidade deve receber um BREVE resumo de 1 ou 2 frases curtas (`source_desc`/`target_desc`) explicando quem ou o que ela é DENTRO DESTE EXATO CONTEXTO do documento analisado.

ESQUEMA PERMITIDO:
ENTIDADES: {entities_str}
RELAÇÕES: {relations_str}

REGRAS FINAIS:
- Proibido triplas genéricas (A está_relacionado_a B).
- Proibido source == target e loops diretos vagos.
- Evite extrações fragmentadas e números flutuantes irrelevantes. Use lógica rigorosa.

TEXTO:
{chunk["text"]}

RETORNE APENAS JSON SEGUINDO ESTE MODELO EXATO:
{{
  "chain_of_thought": "Passo 1: Identifiquei o método X... Passo 2: Notei a instrução do usuário...",
  "triples": [
    {{
      "source": "Nome Técnico e Unificado", 
      "source_type": "TIPO", 
      "source_desc": "Breve resumo sobre esta entidade neste contexto...",
      "target": "Nome Técnico ou Valor Crucial", 
      "target_type": "TIPO", 
      "target_desc": "Breve resumo construtor do papel dessa entidade...",
      "relation": "verbo_infinitivo"
    }}
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
        
        # Upgrade model if custom instructions are provided to guarantee adherence
        processing_model = "gpt-4o" if user_instructions else self.model

        try:
            response = self.client.chat.completions.create(
                model=processing_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Você é um extrator preciso de Grafos de Conhecimento. "
                            "Retorne SEMPRE e APENAS uma lista JSON válida ou objeto com chave 'triples'. "
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
                    # Check if any value is a list of triples
                    for val in content.values():
                        if isinstance(val, list) and len(val) > 0 and isinstance(val[0], dict) and "source" in val[0]:
                            raw_triples = val
                            break

            # Strict validation
            validated = self._validate_triples(raw_triples, valid_types)

            logger.info(
                f"Chunk {chunk.get('index', '?')}: "
                f"{len(raw_triples)} raw → {len(validated)} valid triples"
            )
            return {"triples": validated, "usage": usage, "model": processing_model}

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
            "página", "tabela", "figura", "imagem", "anexo"
        }
        VAGUE_RELATIONS = {
            "está_relacionado_a", "é_associado_com", "relaciona_se",
            "tem_relação", "possui_relação", "faz_parte", "integra",
            "contém", "inclui", "tem"
        }

        seen = set()
        validated = []

        # Type mapping for internal consistency (matching ontology.py)
        TYPE_MAPPING = {
            # ORGANIZACAO
            "EMPRESA": "ORGANIZACAO", "INSTITUICAO": "ORGANIZACAO", "ORGAO": "ORGANIZACAO",
            "SECRETARIA": "ORGANIZACAO", "SETOR": "ORGANIZACAO", "DIVISAO": "ORGANIZACAO",
            "ENTIDADE": "ORGANIZACAO", "GERENCIA": "ORGANIZACAO", "MINISTERIO": "ORGANIZACAO",
            "DEPARTAMENTO": "ORGANIZACAO", "FUNDACAO": "ORGANIZACAO",
            
            # PESSOA
            "AUTOR": "PESSOA", "ESPECIALISTA": "PESSOA", "AGENTE": "PESSOA",
            "INDIVIDUO": "PESSOA", "PESQUISADOR": "PESSOA",
            
            # LOCALIDADE
            "CIDADE": "LOCALIDADE", "ESTADO": "LOCALIDADE", "PAIS": "LOCALIDADE",
            "REGIAO": "LOCALIDADE",
            
            # TEMPO
            "DATA": "TEMPO", "ANO": "TEMPO", "PERIODO": "TEMPO",
            "MARCO_TEMPORAL": "TEMPO", "EPOCA": "TEMPO",
            
            # CONCEITO
            "DEFINICAO": "CONCEITO", "TERMO": "CONCEITO", "CONCEITO_ECONOMICO": "CONCEITO",
            "FENOMENO": "CONCEITO", "IDEIA": "CONCEITO",
            
            # METODOLOGIA
            "METODO": "METODOLOGIA", "TECNICA": "METODOLOGIA", "PROCESSO": "METODOLOGIA",
            "ABORDAGEM": "METODOLOGIA", "PRATICA": "METODOLOGIA",
            
            # INDICADOR
            "INDICADOR_ECONOMICO": "INDICADOR", "METRICA": "INDICADOR",
            "VARIAVEL": "INDICADOR", "DADO": "INDICADOR", "INFORMAÇÃO": "INDICADOR"
        }

        for t in triples:
            if not isinstance(t, dict):
                continue

            source = str(t.get("source", "")).strip()
            target = str(t.get("target", "")).strip()
            relation = str(t.get("relation", "")).strip().lower().replace(" ", "_")
            source_type = str(t.get("source_type", "")).strip().upper()
            target_type = str(t.get("target_type", "")).strip().upper()
            source_desc = str(t.get("source_desc", "")).strip()
            target_desc = str(t.get("target_desc", "")).strip()

            # Map types
            source_type = TYPE_MAPPING.get(source_type, source_type)
            target_type = TYPE_MAPPING.get(target_type, target_type)

            # Required fields check
            if not source or not target or not relation:
                continue

            # Self-loop check
            if source.lower() == target.lower():
                continue

            # Entity quality check
            if self._is_bad_entity(source, BANNED_PATTERNS):
                continue
            if self._is_bad_entity(target, BANNED_PATTERNS):
                continue

            # Vague relation check
            if relation in VAGUE_RELATIONS:
                continue

            # Type validation with fuzzy matching
            if valid_types:
                from rapidfuzz import process, fuzz
                
                # Helper to resolve type or default to a safe fallback
                def resolve_type(stype: str) -> str:
                    stype = stype.upper().strip()
                    if stype in valid_types:
                        return stype
                    
                    # Attempt fuzzy match
                    match = process.extractOne(stype, list(valid_types), scorer=fuzz.token_set_ratio)
                    if match and match[1] > 80: 
                        return match[0]
                    
                    # Try to map to "CONCEITO" if it exists
                    if "CONCEITO" in valid_types: return "CONCEITO"
                    return list(valid_types)[0] if valid_types else "ENTIDADE"

                source_type = resolve_type(source_type)
                target_type = resolve_type(target_type)

            # Deduplication
            triple_key = (source.lower(), target.lower(), relation)
            if triple_key in seen:
                continue
            seen.add(triple_key)

            validated.append({
                "source": source,
                "source_type": source_type,
                "source_desc": source_desc,
                "target": target,
                "target_type": target_type,
                "target_desc": target_desc,
                "relation": relation
            })

        return validated

    @staticmethod
    def _is_bad_entity(name: str, banned: set) -> bool:
        """Returns True if entity name is noise (should be rejected)."""
        # Pure numbers are noise unless they looks like years/dates and we want them
        if name.isdigit() and len(name) != 4: # Keep years like 1994, drop others
            return True
        # Very short names (1-2 chars)
        if len(name) <= 2:
            return True
        # File path patterns
        if '/' in name or '\\' in name or name.endswith(('.pdf', '.csv', '.docx', '.txt')):
            return True
        # Banned generic words
        if name.lower().strip() in banned:
            return True
        return False

    def _parse_json(self, text: str) -> Any:
        """Robustly parses JSON from LLM text output, handling reasoning blocks."""
        import re
        text = text.strip()
        if not text:
            logger.error("LLM returned empty response.")
            return []

        # 1. Remove reasoning blocks
        text = re.sub(r'<thought>.*?</thought>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = text.strip()

        # 2. Direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 3. Strip markdown code fences
        json_match = re.search(r'```(?:json)?\s*([\[\{].*?[\]\}])\s*```', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # 4. Extract outermost [ ] or { }
        start_candidates = [idx for idx in [text.find('['), text.find('{')] if idx != -1]
        end_candidates = [idx for idx in [text.rfind(']'), text.rfind('}')] if idx != -1]

        if start_candidates and end_candidates:
            start_idx = min(start_candidates)
            end_idx = max(end_candidates)
            if end_idx > start_idx:
                try:
                    return json.loads(text[start_idx:end_idx + 1])
                except json.JSONDecodeError:
                    # Try smaller blocks if nested
                    blocks = re.findall(r'[\[\{].*?[\]\}]', text, re.DOTALL)
                    for b in reversed(blocks):
                        try:
                            return json.loads(b)
                        except:
                            continue

        logger.error(f"Failed to parse JSON from response: {text[:300]}...")
        return []
