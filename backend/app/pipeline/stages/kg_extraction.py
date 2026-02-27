from typing import List, Dict, Any
import json
import logging
import httpx
import chromadb
from pathlib import Path
from openai import OpenAI
from app.config import settings, SemanticNodeType
from app.utils import retry_with_exponential_backoff, make_entity_id

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
        
        # ChromaDB for semantic embeddings
        self.chroma_client = chromadb.PersistentClient(path=str(settings.CHROMA_PATH))
        self.semantic_collection = self.chroma_client.get_or_create_collection(
            name=settings.COLLECTION_SEMANTIC_NAME,
            metadata={"hnsw:space": "cosine"}
        )

    def store_entities(self, triples: List[Dict[str, Any]]):
        """
        Extracts unique entities from triples and stores their enriched context in ChromaDB.
        """
        if not triples:
            return

        entities = {} # entity_id -> entity_data
        
        for t in triples:
            # Process Source
            s_name = t.get("source")
            s_type = t.get("source_type", "UNKNOWN")
            s_id = make_entity_id(s_type, s_name)
            
            if s_id not in entities:
                entities[s_id] = {
                    "name": s_name,
                    "type": s_type,
                    "desc": t.get("source_desc", ""),
                    "attributes": t.get("source_attributes", {}),
                    "rels": []
                }
            
            # Process Target
            t_name = t.get("target")
            t_type = t.get("target_type", "UNKNOWN")
            t_id = make_entity_id(t_type, t_name)
            
            if t_id not in entities:
                entities[t_id] = {
                    "name": t_name,
                    "type": t_type,
                    "desc": t.get("target_desc", ""),
                    "attributes": t.get("target_attributes", {}),
                    "rels": []
                }
            
            # Add relationship info to both (for context)
            rel = t.get("relation", "relacionado_com")
            entities[s_id]["rels"].append(f"{rel} -> {t_name}")
            entities[t_id]["rels"].append(f"alvo de {rel} por {s_name}")

        # Upsert to ChromaDB
        for eid, info in entities.items():
            # Build rich contextual text
            attrs_text = "; ".join(f"{k}={v}" for k, v in info["attributes"].items())
            rels_text = "; ".join(info["rels"][:10]) # Cap relations for context length
            
            full_context = (
                f"Entidade: {info['name']}\n"
                f"Tipo: {info['type']}\n"
                f"Descrição: {info['desc']}\n"
                f"Atributos: {attrs_text}\n"
                f"Relações: {rels_text}"
            ).strip()

            self.semantic_collection.upsert(
                ids=[eid],
                documents=[full_context],
                metadatas=[{
                    "node_type": SemanticNodeType["ENTITY"],
                    "entity_id": eid,
                    "name": info["name"],
                    "type": info["type"]
                }]
            )
        
        logger.info(f"Stored {len(entities)} unique entities in semantic collection.")

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

OBJETIVO: Extrair triplas que representam a essência, a lógica, os processos e o CONTEXTO (Épocas, Marcos, Estruturas) do texto.

CADEIA DE ATENÇÃO (Respeite rigorosamente):
1. ANÁLISE INTEGRAL: Identifique não apenas métodos, mas os PILARES do texto. Analise o contexto de forma holística.
2. FILTRO DE RELEVÂNCIA: Ignore ruído técnico de formatação, mas capture marcos que definem o assunto.
3. PADRONIZAÇÃO: Unifique entidades que são a mesma coisa usando nomes formais.
4. ATRIBUTOS DINÂMICOS: Para cada entidade, identifique atributos relevantes conforme o tipo e o contexto. 
   - Exemplos (adapte conforme necessário): 
     * PESSOA: idade, cargo, função principal, afiliação.
     * ORGANIZACAO: área de atuação, sede, importância estratégica, tipo (pública/privada).
     * METODOLOGIA: complexidade, precisão, requisitos, ferramentas bases.
     * INDICADOR: unidade, frequência de atualização, relevância econômica.
5. RESUMO DE ALTA PRECISÃO: Toda entidade deve ter uma descrição detalhada (`source_desc`/`target_desc`) de 2 a 4 frases completas, explicando sua função específica, importância e como ela se encaixa no cenário descrito no documento. Evite descrições genéricas.

ESQUEMA PERMITIDO:
ENTIDADES: {entities_str}
RELAÇÕES: {relations_str}

REGRAS FINAIS:
- Proibido triplas genéricas (A está_relacionado_a B).
- Proibido source == target.

TEXTO:
{chunk["text"]}

RETORNE APENAS JSON SEGUINDO ESTE MODELO EXATO:
{{
  "chain_of_thought": "Análise sobre como os atributos foram mapeados...",
  "triples": [
    {{
      "source": "Nome Técnico", 
      "source_type": "TIPO", 
      "source_desc": "Descrição detalhada e contextualizada (mínimo 2 frases)...",
      "source_attributes": {{ "atributo1": "valor", "atributo2": "valor" }},
      "target": "Nome Técnico ou Valor", 
      "target_type": "TIPO", 
      "target_desc": "Descrição detalhada e contextualizada (mínimo 2 frases)...",
      "target_attributes": {{ "atributo1": "valor", "atributo2": "valor" }},
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

        @retry_with_exponential_backoff()
        def _call_llm(messages, model):
            return self.client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.0
            )

        try:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "Você é um extrator preciso de Grafos de Conhecimento. "
                        "Retorne SEMPRE e APENAS uma lista JSON válida ou objeto com chave 'triples'. "
                        "Se não houver nada para extrair, retorne []."
                    )
                },
                {"role": "user", "content": prompt}
            ]
            response = _call_llm(messages, processing_model)

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
            source_attrs = t.get("source_attributes", {})
            target_attrs = t.get("target_attributes", {})

            # Ensure attributes are dicts
            if not isinstance(source_attrs, dict): source_attrs = {}
            if not isinstance(target_attrs, dict): target_attrs = {}

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
                "source_attributes": source_attrs,
                "target": target,
                "target_type": target_type,
                "target_desc": target_desc,
                "target_attributes": target_attrs,
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
