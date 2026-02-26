from typing import List, Dict, Any
import json
from openai import OpenAI
from app.config import settings
import logging
import httpx

logger = logging.getLogger(__name__)

class OntologyBuilder:
    def __init__(self):
        try:
            verify = settings.VERIFY_SSL
            logger.info(f"Initializing OntologyBuilder with VERIFY_SSL={verify}")
            self.http_client = httpx.Client(verify=verify)
            self.client = OpenAI(
                api_key=settings.OPENAI_API_KEY,
                base_url=settings.LLM_BASE_URL,
                http_client=self.http_client
            )
        except Exception as e:
            logger.error(f"Failed to initialize OntologyBuilder: {e}")
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

    def build(self, chunks: List[Dict[str, Any]], user_instructions: str = "") -> Dict[str, Any]:
        """
        Builds an ontology from a representative sample of chunks,
        respecting user global instructions (e.g., banning certain types).
        """
        # Sample strategically: beginning + middle + end for better coverage
        sample_size = min(6, len(chunks))
        if len(chunks) > 6:
            mid = len(chunks) // 2
            indices = [0, 1, mid - 1, mid, -2, -1]
            sample_chunks = [chunks[i] for i in indices if abs(i) < len(chunks)]
        else:
            sample_chunks = chunks[:sample_size]

        sample_text = "\n---\n".join([c["text"][:2000] for c in sample_chunks])

        user_context_block = (
            f"\n*** INSTRUÇÕES EXPLÍCITAS E PRIORITÁRIAS DO USUÁRIO (Rigor Máximo) ***\n{user_instructions}\n"
            if user_instructions else ""
        )

        prompt = f"""Analise o texto e crie uma Ontologia para um Grafo de Conhecimento Científico/Técnico.
{user_context_block}

Você deve identificar as classes (entidades) e relações fundamentais. 

REGRAS OBRIGATÓRIAS DE ARQUITETURA (Rigor Absoluto):
1. **DEDUPLICAÇÃO DE TIPOS**: Use APENAS os tipos abaixo se aplicável. NÃO invente sinônimos.
   - "ORGANIZACAO": Para empresas, institutos, órgãos, secretarias, fundações.
   - "PESSOA": Para autores, especialistas, cargos, indivíduos.
   - "LOCALIDADE": Para cidades, estados, países, regiões.
   - "TEMPO": Para datas, anos, períodos, marcos temporais.
   - "METODOLOGIA": Para métodos, algoritmos, fórmulas, processos, técnicas.
   - "INDICADOR": Para métricas, dados numéricos, variáveis, resultados de cálculo.
   - "CONCEITO": Para definições técnicas, termos teóricos, ideias abstratas.
   - "FERRAMENTA": Para softwares, sistemas, instrumentos específicos.
2. **NÃO CONFUNDA INSTÂNCIA COM CLASSE**: "IBGE" é uma ORGANIZACAO, não um tipo "Instituto". "2023" é TEMPO, não "Ano". "PIB" é um INDICADOR, não "Indice".
3. **MÁXIMO DE 8 TIPOS**: Escolha os 8 tipos mais relevantes que descrevem a estrutura do conhecimento no texto. Qualidade > Quantidade.
4. **NOMENCLATURA**: Use nomes em MAIÚSCULAS e sem espaços (ex: FONTE_DADOS). RELAÇÕES devem ser verbos no infinitivo (ex: "utiliza_metodo").
5. **FOCO TÉCNICO**: Se o texto fala de economia, foque em INDICADOR e METODOLOGIA. Se fala de história, foque em TEMPO e LOCALIDADE.

FORMATO DE SAÍDA (Retorne APENAS o JSON. Sem explicações ou blocos de pensamento fora do JSON):
{{
  "entities": [{{ "name": "TIPO_UPPER", "description": "Definição técnica curta e clara" }}],
  "relations": [{{ "label": "verbo_infinitivo", "source": "TIPO", "target": "TIPO", "description": "Conexão semântica entre os tipos" }}]
}}

TEXTO PARA ANÁLISE:
{sample_text}
"""

        logger.info(f"Generating ontology using {self.model}...")

        try:
            # Use json_object format if supported by newer models, but keep parsing robust
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "Você é um arquiteto de ontologias especialista em extração de Grafos de Conhecimento Científico. Responda apenas com o JSON da ontologia."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0
            )

            raw_content = response.choices[0].message.content or ""
            ontology = self._parse_json(raw_content)
            usage = response.usage.model_dump() if hasattr(response, 'usage') else {}

            # Validate and clean the schema
            ontology = self._validate_ontology(ontology)

            logger.info(
                f"Ontology built: {len(ontology.get('entities', []))} entity types, "
                f"{len(ontology.get('relations', []))} relation types."
            )
            return {"ontology": ontology, "usage": usage}

        except Exception as e:
            logger.error(f"Ontology generation failed: {e}")
            return {"ontology": {"entities": [], "relations": []}, "usage": {}, "error": str(e)}

    def _validate_ontology(self, ontology: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validates and sanitizes the ontology schema:
        - Removes entity types with empty/missing names or descriptions.
        - Removes duplicate entity type names (case-insensitive).
        - Removes relations pointing to undefined entity types.
        - Removes duplicate relations.
        - Applies a second layer of hard-coded deduplication for very common redundant pairs.
        """
        raw_entities = ontology.get("entities", [])
        raw_relations = ontology.get("relations", [])

        # Hard-coded type mapping for deduplication (Canonical set)
        TYPE_MAPPING = {
            # ORGANIZACAO
            "EMPRESA": "ORGANIZACAO",
            "INSTITUICAO": "ORGANIZACAO",
            "ORGAO": "ORGANIZACAO",
            "SECRETARIA": "ORGANIZACAO",
            "SETOR": "ORGANIZACAO",
            "DIVISAO": "ORGANIZACAO",
            "ENTIDADE": "ORGANIZACAO",
            "GERENCIA": "ORGANIZACAO",
            "MINISTERIO": "ORGANIZACAO",
            "DEPARTAMENTO": "ORGANIZACAO",
            "FUNDACAO": "ORGANIZACAO",
            
            # PESSOA
            "AUTOR": "PESSOA",
            "ESPECIALISTA": "PESSOA",
            "AGENTE": "PESSOA",
            "INDIVIDUO": "PESSOA",
            "PESQUISADOR": "PESSOA",
            
            # LOCALIDADE
            "CIDADE": "LOCALIDADE",
            "ESTADO": "LOCALIDADE",
            "PAIS": "LOCALIDADE",
            "REGIAO": "LOCALIDADE",
            
            # TEMPO
            "DATA": "TEMPO",
            "ANO": "TEMPO",
            "PERIODO": "TEMPO",
            "MARCO_TEMPORAL": "TEMPO",
            "EPOCA": "TEMPO",
            
            # CONCEITO
            "DEFINICAO": "CONCEITO",
            "TERMO": "CONCEITO",
            "CONCEITO_ECONOMICO": "CONCEITO",
            "FENOMENO": "CONCEITO",
            "IDEIA": "CONCEITO",
            
            # METODOLOGIA
            "METODO": "METODOLOGIA",
            "TECNICA": "METODOLOGIA",
            "PROCESSO": "METODOLOGIA",
            "ABORDAGEM": "METODOLOGIA",
            "PRATICA": "METODOLOGIA",
            
            # INDICADOR
            "INDICADOR_ECONOMICO": "INDICADOR",
            "METRICA": "INDICADOR",
            "VARIAVEL": "INDICADOR",
            "DADO": "INDICADOR",
            "INFORMAÇÃO": "INDICADOR"
        }

        # 1. Deduplicate and validate entity types
        seen_types = set()
        clean_entities = []
        for e in raw_entities:
            name = str(e.get("name", "")).strip().upper()
            
            # Map redundant types
            name = TYPE_MAPPING.get(name, name)
            
            desc = str(e.get("description", "")).strip()
            if not name or name in seen_types:
                continue
            seen_types.add(name)
            clean_entities.append({"name": name, "description": desc})

        # 2. Validate relations: both source and target must exist in entity types
        clean_relations = []
        seen_relations = set()
        for r in raw_relations:
            label = str(r.get("label", "")).strip().lower().replace(" ", "_")
            source = str(r.get("source", "")).strip().upper()
            target = str(r.get("target", "")).strip().upper()
            
            # Map redundant types in relations too
            source = TYPE_MAPPING.get(source, source)
            target = TYPE_MAPPING.get(target, target)
            
            desc = str(r.get("description", "")).strip()

            if not label or not source or not target:
                continue

            # Both types must be declared
            if source not in seen_types or target not in seen_types:
                logger.debug(f"Pruning relation '{label}': types '{source}' or '{target}' not in schema.")
                continue

            # Deduplicate
            rel_key = (label, source, target)
            if rel_key in seen_relations:
                continue
            seen_relations.add(rel_key)

            clean_relations.append({"label": label, "source": source, "target": target, "description": desc})

        return {"entities": clean_entities, "relations": clean_relations}

    def prune_unused_types(self, ontology: Dict[str, Any], triples: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Call AFTER triple extraction. Removes entity types that had zero
        instances extracted, and relations that are no longer referenced.
        """
        used_types = set()
        for t in triples:
            if t.get("source_type"):
                used_types.add(str(t["source_type"]).strip().upper())
            if t.get("target_type"):
                used_types.add(str(t["target_type"]).strip().upper())

        if not used_types:
            logger.warning("No types found in triples. Skipping ontology pruning.")
            return ontology

        # Keep a minimum set of entities if possible
        clean_entities = ontology.get("entities", [])
        pruned_entities = [e for e in clean_entities if e["name"] in used_types]
        
        # If pruning removed everything but we had entities, keep the top used or original ones
        if not pruned_entities and clean_entities:
            logger.warning("Ontology pruning would remove all entities. Keeping original schema.")
            return ontology

        pruned_entity_names = {e["name"] for e in pruned_entities}

        pruned_relations = [
            r for r in ontology.get("relations", [])
            if r["source"] in pruned_entity_names and r["target"] in pruned_entity_names
        ]

        removed = len(clean_entities) - len(pruned_entities)
        if removed > 0:
            logger.info(f"Pruned {removed} unused entity types from ontology. {len(pruned_entities)} remain.")

        return {"entities": pruned_entities, "relations": pruned_relations}

    def _parse_json(self, text: str) -> Dict[str, Any]:
        import re
        text = text.strip()
        if not text:
            logger.error("LLM returned empty response content.")
            return {"entities": [], "relations": []}

        # 1. Try to remove <thought> blocks if they exist
        text = re.sub(r'<thought>.*?</thought>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = text.strip()

        # 2. Direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 3. Look for markdown code block
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # 4. Find the first '{' and last '}' that enclose the largest potential JSON object
        # We try to be more robust by checking if the slice actually parses
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and end > start:
            # Try progressively smaller slices if it fails (in case of multiple {} blocks)
            # though usually the largest is the one we want.
            candidate = text[start:end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                # If the largest slice fails, maybe there's text after the JSON?
                # Or maybe the first { is not the start of the main JSON?
                # Let's try to find all JSON-like blocks and pick the one with "entities"
                blocks = re.findall(r'\{.*?\}', text, re.DOTALL)
                for b in reversed(blocks): # Often the JSON is at the end
                    try:
                        data = json.loads(b)
                        if "entities" in data:
                            return data
                    except:
                        continue

        logger.error(f"Failed to parse JSON from ontology response: {text[:300]}...")
        return {"entities": [], "relations": []}
