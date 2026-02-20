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

Você deve identificar as classes (entidades) e relações fundamentais. Foque em METODOLOGIA, MATEMÁTICA, DADOS e CONCEITOS ESTRUTURAIS.

REGRAS DE OURO (SEM EXCEÇÃO):
1. **NÃO CONFUNDA EXEMPLOS COM CLASSES**: Se o texto cita "tomate", o tipo NÃO é "Tomate" nem "Setor Economico" (a menos que o texto seja sobre agronegócio). Se o texto fala de cálculo de PIB, "tomate" é apenas um DADO ou PRODUTO, não um setor. Classe correta: "VARIAVEL", "INDICADOR", "PRODUTO".
2. **PRIORIDADE TÉCNICA**: Se o usuário pediu foco em "matemática e metodologia", priorize tipos como "METODO_CALCULO", "EQUACAO", "FONTE_DADOS", "INDICADOR_ESTATISTICO".
3. **RIGOR NAS INSTRUÇÕES**: Se o usuário proibiu algo, REMOVA totalmente do esquema.
4. **QUALIDADE > QUANTIDADE**: Evite criar 20 tipos. Use de 5 a 12 tipos bem definidos que cubram o propósito técnico do texto.
5. **DEDUPLICAÇÃO**: Não crie tipos redundantes (ex: "Empresa" e "Organizacao"). Use apenas "ORGANIZACAO".

ENTIDADES SUGERIDAS (Adapte ao domínio):
- METODOLOGIA: Algoritmos, fórmulas, passos de processo.
- INDICADOR: Métricas calculadas (ex: PIB, VBP).
- FONTE_DADOS: De onde vem a informação (ex: Censo, Pesquisa).
- ORGANIZACAO: Institutos, empresas, órgãos.
- CONCEITO: Definições teóricas.

RELAÇÕES (Use verbos precisos):
- "calcula_via", "utiliza_dado", "pertence_a", "aplica_metodo", "publicado_por".

FORMATO DE SAÍDA (Obrigatório JSON):
{{
  "entities": [{{ "name": "TIPO_UPPER", "description": "Definição técnica + o que NÃO incluir" }}],
  "relations": [{{ "label": "verbo_infinitivo", "source": "TIPO", "target": "TIPO", "description": "Ação semântica" }}]
}}

TEXTO PARA ANÁLISE:
{sample_text}
"""

        logger.info(f"Generating ontology using {self.model}...")

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "Você é um arquiteto de ontologias especialista em extração de Grafos de Conhecimento Científico."},
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
        """
        raw_entities = ontology.get("entities", [])
        raw_relations = ontology.get("relations", [])

        # 1. Deduplicate and validate entity types
        seen_types = set()
        clean_entities = []
        for e in raw_entities:
            name = str(e.get("name", "")).strip().upper()
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
            return ontology  # Nothing to prune if no triples

        pruned_entities = [e for e in ontology.get("entities", []) if e["name"] in used_types]
        pruned_entity_names = {e["name"] for e in pruned_entities}

        pruned_relations = [
            r for r in ontology.get("relations", [])
            if r["source"] in pruned_entity_names and r["target"] in pruned_entity_names
        ]

        removed = len(ontology.get("entities", [])) - len(pruned_entities)
        if removed > 0:
            logger.info(f"Pruned {removed} unused entity types from ontology.")

        return {"entities": pruned_entities, "relations": pruned_relations}

    def _parse_json(self, text: str) -> Dict[str, Any]:
        text = text.strip()
        if not text:
            logger.error("LLM returned empty response content.")
            return {"entities": [], "relations": []}

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        import re
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass

        logger.error(f"Failed to parse JSON from ontology response: {text[:300]}...")
        return {"entities": [], "relations": []}
