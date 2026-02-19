from typing import List, Dict, Any
import json
from openai import OpenAI
from app.config import settings
import logging
import httpx

logger = logging.getLogger(__name__)

ONTOLOGY_PROMPT = """
Analise o seguinte texto e crie um esquema de Ontologia PRECISO e MÍNIMO para um Grafo de Conhecimento.

REGRAS CRÍTICAS:
1. **QUALIDADE > QUANTIDADE**: Prefira 10 tipos de entidades reais a 50 tipos genéricos.
2. **Sem tipos fantasmas**: Só inclua um tipo de entidade se você consegue citar pelo menos 2 exemplos concretos que aparecem no texto.
3. **Relações com semântica real**: Cada relação deve expressar um fato verificável. Proibido: "está_relacionado_a", "faz_parte_de" genérico, "é_associado_com".
4. **Verbos de ação e direção**: Use relações unidirecionais com verbos claros: "emprega", "financia", "calcula_via", "é_componente_de", "produz", "localiza_em".
5. **Português técnico acessível**: Nomes em português, sem abreviações obscuras.

ENTIDADES (máx 20 - atenção: SÓ inclua se existem instâncias reais no texto):
- PESSOA: Nomes de pessoas físicas (ex: "João Silva", "Maria Aparecida")
- ORGANIZAÇÃO: Empresas, fundações, órgãos públicos com nome (ex: "IBGE", "Seade")
- CONCEITO: Ideias, metodologias, indicadores (ex: "PIB", "Taxa de Fecundidade")
- LOCAL: Localidades geográficas com nome (ex: "São Paulo", "Brasil")
- EVENTO: Ocorrências com data ou período definido (ex: "Censo 2022")
- Adapte: Crie tipos específicos do domínio do texto SE houver instâncias reais.

RELAÇÕES (máx 30):
- Apenas relações que aparecem explicitamente no texto.
- Formato: verbo_no_infinitivo ou substantivo_ação (ex: "publica", "contém", "emprega_método")

FORMATO DE SAÍDA: APENAS JSON, sem texto extra.
{
  "entities": [
    {"name": "TIPO", "description": "O que representa. Exemplo: [2+ exemplos do texto]"}
  ],
  "relations": [
    {"label": "verbo_acao", "source": "TIPO_ORIGEM", "target": "TIPO_DESTINO", "description": "O que essa relação significa"}
  ]
}
"""


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

    def build(self, chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Builds an ontology from a representative sample of chunks,
        then prunes entity types with no real instances.
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

        logger.info(f"Generating ontology using {self.model}...")

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": ONTOLOGY_PROMPT},
                    {"role": "user", "content": sample_text}
                ],
                temperature=0.0  # Deterministic for schema generation
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
