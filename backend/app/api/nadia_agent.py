import logging
import json
from typing import List, Dict, Any, Optional
from openai import OpenAI
import numpy as np
from sympy import sympify, diff, symbols, latex
import numpy_financial as npf
import statistics as stats_lib

from langchain_openai import ChatOpenAI
from langchain_core.tools import Tool
from langchain_core.messages import HumanMessage
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver

from app.config import settings, SemanticNodeType
from app.api.rag_system import GraphRAGSystem
from app.graph.semantic_graph_manager import SemanticKnowledgeGraph

logger = logging.getLogger(__name__)

class Nadia:
    """
    Expert Assistant specialized in deep document analysis via GraphRAG.
    Orchestrates structural (P1) and semantic (P2) pipelines using LangGraph.
    """
    def __init__(self, openai_client: OpenAI):
        self.openai_client = openai_client
        
        # Initialize RAG System (Structural)
        self.rag = GraphRAGSystem(openai_client)
        
        # Initialize Semantic Graph (P2)
        self.skg = SemanticKnowledgeGraph.load(settings.STORAGE_DIR)
        
        # Agent Logic
        self.llm = ChatOpenAI(
            model=settings.OPENAI_MODEL,
            openai_api_key=settings.OPENAI_API_KEY,
            openai_api_base=settings.LLM_BASE_URL,
            temperature=0
        )
        self.memory = MemorySaver()
        self.tools = self._build_tools()
        
        self.agent = create_react_agent(
            self.llm,
            self.tools,
            checkpointer=self.memory,
            prompt=self._system_prompt()
        )

    def _system_prompt(self) -> str:
        p1_status = "ATIVO" if not self.rag.kg.is_empty() else "INDISPONIVEL (Aguardando ingestão)"
        p2_status = "ATIVO" if not self.skg.is_empty() else "INDISPONIVEL (Aguardando processamento semântico)"

        return (
            "Você é a Nadia, uma assistente virtual especializada em análise profunda de documentos PDF.\n"
            f"Pipeline 1 (RAG Estrutural): {p1_status}\n"
            f"Pipeline 2 (Grafo Semântico): {p2_status}\n\n"

            "REGRA OBRIGATÓRIA - NUNCA IGNORE:\n"
            "Toda pergunta que não seja saudação ou conversa genérica DEVE começar "
            "com uma chamada a ferramenta ANTES de qualquer resposta. "
            "NUNCA diga 'não tenho os dados' sem antes ter consultado as ferramentas.\n\n"

            "FLUXO DE DECISÃO OBRIGATÓRIO:\n"
            "1. É saudação ou conversa genérica? (oi, obrigado, quem é você...)\n"
            "   -> SIM: responda diretamente.\n"
            "   -> NÃO: vá para 2.\n\n"
            "2. A pergunta é sobre RELAÇÕES entre entidades/conceitos?\n"
            "   (como X se relaciona com Y, quem impacta Z, dependências entre...)\n"
            "   -> SIM: chame 'consultar_grafo_semantico' primeiro.\n"
            "   -> NÃO: vá para 3.\n\n"
            "3. A pergunta envolve números, percentuais, tabelas ou séries?\n"
            "   -> SIM: chame 'extrair_tabela' primeiro.\n"
            "   -> NÃO: chame 'consultar_documentos' primeiro.\n\n"
            "4. A resposta exige cálculo com valores encontrados?\n"
            "   -> SIM: chame 'math_calculator' com os valores obtidos.\n"
            "   -> NÃO: formule a resposta final.\n\n"
            "5. Cite sempre: documento + página (Pipeline 1) ou entidade + relação (Pipeline 2).\n\n"

            "FORMATO DA RESPOSTA FINAL:\n"
            "- Estruturada com tópicos quando pertinente.\n"
            "- Cite fonte: nome do documento e página, ou entidade e sua categoria.\n"
            "- Se dados parciais: informe o que foi e o que não foi encontrado.\n"
            "- Responda em português do Brasil."
        )

    def _build_tools(self) -> list[Tool]:
        return [
            Tool(
                name="consultar_documentos",
                func=self._tool_query,
                description=(
                    "PRINCIPAL FERRAMENTA DE CONSULTA. Busca informações, fatos e análises nos documentos "
                    "usando GraphRAG. Use para qualquer pergunta sobre o conteúdo do texto. "
                    "Input: pergunta completa do usuário."
                ),
            ),
            Tool(
                name="extrair_tabela",
                func=self._tool_table,
                description=(
                    "Extrai dados de tabelas e séries numéricas. Use para valores, percentuais e comparações. "
                    "Input: descrição do dado ou tabela desejada."
                ),
            ),
            Tool(
                name="consultar_grafo_semantico",
                func=self._tool_semantic_graph,
                description=(
                    "Navega o grafo semântico de entidades. Use para entender RELAÇÕES, conexões e impactos "
                    "entre empresas, indicadores ou conceitos. Ex: 'como o PIB impacta o consumo?'. "
                    "Input: nome de entidade ou conceito para explorar."
                ),
            ),
            Tool(
                name="explorar_grafo",
                func=self._tool_graph,
                description=(
                    "Navega a estrutura física interna do PDF. Use para saber seções disponíveis e organização. "
                    "Input: nome de seção ou documento."
                ),
            ),
            Tool(
                name="math_calculator",
                func=self._tool_math,
                description=(
                    "Realiza cálculos financeiros e matemáticos. Use SOMENTE após obter os dados dos documentos. "
                    "Formatos: eval:<expressão> | pct:<parte>,<total> | growth:<ini>,<fim> | npv:<taxa>,[fluxos] | irr:[fluxos]"
                ),
            ),
        ]

    # ── Implementations ────────────────────────────────────────

    def _tool_query(self, question: str) -> str:
        res = self.rag.query(question)
        return res.get("context", "Nenhuma informação relevante encontrada.")

    def _tool_table(self, query: str) -> str:
        res = self.rag.query(f"Extraia dados de tabelas e series numericas sobre: {query}", top_k_faiss=8, hop_depth=1)
        return res.get("context", "Nenhuma tabela encontrada.")

    def _tool_semantic_graph(self, query: str) -> str:
        if self.skg.is_empty():
            return "Grafo semântico ainda não foi gerado."
            
        out = []
        matching_ids = self.skg.find_entity(query)[:5]
        
        if not matching_ids:
            return f"Nenhuma entidade encontrada com o nome '{query}'."

        for nid in matching_ids:
            ctx = self.skg.get_entity_context(nid)
            out.append(f"\nEntidade: {ctx.get('name', nid)}")
            out.append(f"  Categoria: {ctx.get('category', '?')}")
            if ctx.get("context"):
                out.append(f"  Contexto: {ctx['context'][:300]}")
            
            neighbors = ctx.get("neighbors", [])
            if neighbors:
                out.append("  Relacoes:")
                for nb in neighbors[:10]:
                    direction = "->" if self.skg.G.has_edge(nid, nb["id"]) else "<-"
                    out.append(f"    {direction}[{nb['edge_type']}] {nb['name']} ({nb['node_type']})")
        
        return "\n".join(out)

    def _tool_graph(self, query: str) -> str:
        kg = self.rag.kg
        if kg.is_empty():
            return "Grafo estrutural vazio."
            
        query_lower = query.lower()
        matching = [
            nid for nid in kg.G.nodes()
            if query_lower in kg.G.nodes[nid].get("label", "").lower()
        ][:5]

        if not matching:
            return "Nenhuma seção ou documento encontrado com esse nome."

        out = []
        for nid in matching:
            data = kg.G.nodes[nid]
            out.append(f"\n{data.get('label', nid)} [{data.get('type','?')}]")
            for s in list(kg.G.successors(nid))[:8]:
                et  = kg.G[nid][s].get("type", "")
                lbl = kg.G.nodes[s].get("label", s)[:40]
                out.append(f"  ->[{et}] {lbl}")
        
        return "\n".join(out)

    def _tool_math(self, input_str: str) -> str:
        try:
            tipo, args = "eval", input_str.strip()
            if ":" in input_str:
                parts = input_str.split(":", 1)
                tipo = parts[0].strip().lower()
                args = parts[1].strip()

            if tipo == "eval":
                r = sympify(args)
                return f"Resultado: {float(r):.4f}"
            elif tipo == "pct":
                parte, total = (float(v) for v in args.split(","))
                return f"Percentual = {(parte / total) * 100:.2f}%"
            elif tipo == "growth":
                ini, fim = (float(v) for v in args.split(","))
                return f"Variacao = {((fim - ini) / ini) * 100:.2f}%"
            elif tipo == "npv":
                rate, cf = eval(args)
                return f"VPL = R$ {npf.npv(rate, cf):,.2f}"
            elif tipo == "irr":
                return f"TIR = {npf.irr(eval(args)) * 100:.2f}%"
            else:
                return f"Resultado: {float(sympify(args)):.4f}"
        except Exception as e:
            return f"Erro no cálculo: {e}. Use formato 'tipo: argumentos'"

    async def ask(self, question: str, thread_id: str = "default_session") -> str:
        """Async method to invoke the agent."""
        config = {"configurable": {"thread_id": thread_id}}
        try:
            # We wrap the sync invoke in a way that respects the async nature of the request
            # In a real heavy app, we'd use a thread pool, but for now invoke is fine.
            result = self.agent.invoke(
                {"messages": [HumanMessage(content=question)]},
                config=config,
            )
            return result["messages"][-1].content
        except Exception as e:
            logger.error(f"Erro no agente: {e}")
            return f"Erro ao processar sua pergunta: {e}"
