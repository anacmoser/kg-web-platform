# Knowledge Graph Web Platform

Uma plataforma web avançada para transformar documentos heterogêneos (PDF, CSV, DOCX) em **grafos de conhecimento interativos**, utilizando extração via LLM, análise semântica profunda e um agente conversacional inteligente.

---

## ✨ Funcionalidades Principais

| Recurso | Descrição |
|---|---|
| 🧠 **Nadia (Agente IA)** | Assistente conversacional baseada em LangGraph (ReAct) especializada em análise de documentos via GraphRAG |
| 🔍 **GraphRAG Multimodal** | Recuperação que combina contexto estrutural (chunks + FAISS) e semântico (entidades + ChromaDB) |
| ⚙️ **Pipeline de 2 Estágios** | Extração estrutural (P1) + Extração semântica de entidades via LLM (P2) |
| 🕸️ **Visualização Interativa** | Exploração de grafos em tempo real via Cytoscape.js com layout, filtros e busca |
| 🗣️ **TTS Local (Kokoro-82M)** | Síntese de voz de alta qualidade rodando 100% local (sem custo de API) |
| 💰 **Dashboard Financeiro** | Monitoramento em tempo real de tokens consumidos, custos e economia |
| 📊 **Ontologia** | Visualizador dos tipos de entidade e relações descobertos automaticamente |

---

## ⚡ Início Rápido (Windows)

A forma mais fácil de iniciar o projeto é pelo script de automação na raiz:

```powershell
.\start.bat
```

O script irá automaticamente:
1. Criar o ambiente virtual Python em `backend\venv` (se não existir)
2. Instalar todas as dependências backend (`pip install -r requirements.txt`)
3. Instalar as dependências frontend (`npm install`, se necessário)
4. Abrir dois terminais separados — um para o backend, outro para o frontend

> **Backend:** `http://localhost:5000`  
> **Frontend:** `http://localhost:5173`

---

## 🛠️ Instalação Manual

### Pré-requisitos

- **Python 3.13+**
- **Node.js 18+** (com npm)
- **OpenAI API Key**
- *(Opcional)* Redis para cache persistente

### 1. Clone o Repositório

```bash
git clone <url-do-repo>
cd kg-web-platform
```

### 2. Configuração do Backend

```bash
cd backend

# Criar e ativar o ambiente virtual
python -m venv venv

# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# Instalar dependências
pip install -r requirements.txt

# Configurar variáveis de ambiente
copy .env.example .env
# Edite o arquivo .env e preencha sua OPENAI_API_KEY
```

### 3. Configuração do Frontend

```bash
cd frontend

# Instalar dependências
npm install
```

---

## ▶️ Executando a Aplicação

### Backend (Terminal 1)

```bash
cd backend
venv\Scripts\activate   # Windows
python main.py
```

O servidor FastAPI sobe em `http://localhost:5000`.  
A documentação interativa da API fica em `http://localhost:5000/docs`.

### Frontend (Terminal 2)

```bash
cd frontend
npm run dev
```

A interface React fica disponível em `http://localhost:5173`.

---

## 🔧 Configuração

### Variáveis de Ambiente (`backend/.env`)

```bash
# ── Obrigatório ──────────────────────────────────────────
OPENAI_API_KEY=sk-your-key-here

# ── Modelo LLM ───────────────────────────────────────────
# Modelo padrão: gpt-4o (altere para gpt-4o-mini para menor custo)
OPENAI_MODEL=gpt-4o

# ── Banco de Dados ────────────────────────────────────────
# SQLite (padrão, sem instalação necessária):
DATABASE_URL=sqlite:///./sql_app.db
# PostgreSQL (opcional):
# DATABASE_URL=postgresql://user:password@localhost/dbname

# ── Cache (Redis) ─────────────────────────────────────────
# Se indisponível, o sistema usa cache em memória automaticamente
REDIS_URL=redis://localhost:6379/0

# ── Segurança ─────────────────────────────────────────────
SECRET_KEY=your-secret-key-change-in-production

# ── Pipeline ──────────────────────────────────────────────
MAX_WORKERS=2
CACHE_TTL=604800   # 7 dias (em segundos)

# ── CORS ──────────────────────────────────────────────────
CORS_ORIGINS=http://localhost:3000,http://localhost:5173
```

### Precificação de Modelos (em `config.py`)

| Modelo | Input (por 1M tokens) | Output (por 1M tokens) |
|---|---|---|
| `gpt-4o-mini` | $0.15 | $0.60 |
| `gpt-4o` | $2.50 | $10.00 |
| `o1-mini` | $3.00 | $12.00 |

### Modo Lite (Sem Redis / Sem PostgreSQL)

O sistema detecta automaticamente a indisponibilidade de serviços externos e faz fallback:
- Cache **em memória** no lugar do Redis
- **SQLite** no lugar do PostgreSQL
- `MAX_WORKERS=1` para baixo consumo de recursos

---

## 🏗️ Arquitetura

```
kg-web-platform/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── nadia_agent.py        # Agente Nadia (LangGraph ReAct)
│   │   │   ├── rag_system.py         # GraphRAG System (FAISS + ChromaDB)
│   │   │   ├── usage_tracker.py      # Rastreamento de custos e tokens
│   │   │   ├── local_audio.py        # TTS local via Kokoro-ONNX
│   │   │   ├── seade_kb.py           # Base de conhecimento SEADE
│   │   │   └── routes/
│   │   │       ├── documents.py      # Upload e gestão de documentos
│   │   │       ├── pipeline.py       # Disparo e status do pipeline
│   │   │       ├── graphs.py         # Consulta ao grafo gerado
│   │   │       ├── ontology.py       # Consulta à ontologia
│   │   │       └── nadia.py          # Endpoints do chat da Nadia
│   │   ├── pipeline/
│   │   │   ├── orchestrator.py       # Coordenador do pipeline completo
│   │   │   └── stages/
│   │   │       ├── structural_extractor.py  # E1: Extração estrutural (PyMuPDF)
│   │   │       ├── chunking.py              # E2: Chunking semântico
│   │   │       ├── extraction.py            # E3: Indexação FAISS
│   │   │       ├── ontology.py              # E4: Descoberta de ontologia (LLM)
│   │   │       ├── kg_extraction.py         # E5: Extração de entidades (LLM)
│   │   │       ├── normalization.py         # E6: Normalização e deduplicação
│   │   │       └── graph_builder.py         # E7: Construção do grafo (NetworkX)
│   │   ├── graph/
│   │   │   └── serializers/
│   │   │       └── graph_serializer.py      # Serialização JSON do grafo
│   │   ├── config.py                 # Configurações e constantes globais
│   │   └── utils.py                  # Utilitários compartilhados
│   ├── main.py                       # Ponto de entrada (Uvicorn + FastAPI)
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── UploadPage.jsx        # Upload e disparo do pipeline
│   │   │   ├── VisualizePage.jsx     # Visualização interativa do grafo
│   │   │   └── OntologyPage.jsx      # Visualizador de tipos e relações
│   │   ├── components/
│   │   │   ├── SharedComponents.jsx  # Componentes reutilizáveis de UI
│   │   │   └── JobRepository.jsx     # Listagem de jobs processados
│   │   ├── api/                      # Camada de integração com o backend
│   │   ├── App.jsx                   # Roteamento principal (Wouter)
│   │   └── main.jsx
│   ├── package.json
│   └── vite.config.js
├── start.bat                         # Script de automação (Windows)
└── README.md
```

### Stack Tecnológica

**Backend**
| Camada | Tecnologia |
|---|---|
| API REST | FastAPI + Uvicorn |
| Agente IA | LangGraph (ReAct) + LangChain |
| LLM | OpenAI (`gpt-4o` por padrão) |
| Extração de PDFs | PyMuPDF + pymupdf4llm |
| Busca Vetorial | FAISS (estrutural) + ChromaDB (semântico) |
| Grafo de Conhecimento | NetworkX |
| Cache | Redis (ou fallback em memória) |
| TTS Local | Kokoro-ONNX |
| Matemática/Finanças | SymPy, NumPy, numpy-financial |

**Frontend**
| Camada | Tecnologia |
|---|---|
| Framework | React 18 + Vite |
| Roteamento | Wouter |
| Visualização de Grafos | Cytoscape.js |
| Estilos | Tailwind CSS |
| Animações | Framer Motion |
| Ícones | Lucide React |
| Data Fetching | SWR |

---

## 📡 API — Endpoints Principais

### Documentos

```http
POST /api/v1/documents/upload
Content-Type: multipart/form-data

file: <binary>
```

### Pipeline

```http
POST /api/v1/pipeline/start
Content-Type: application/json

{
  "filenames": ["documento.pdf"],
  "config": {}
}
```

```http
GET /api/v1/pipeline/status/{job_id}
```

### Grafo e Ontologia

```http
GET /api/v1/graphs/{job_id}
GET /api/v1/ontology/{job_id}
```

### Nadia (Chat)

```http
POST /api/v1/nadia/chat
Content-Type: application/json

{
  "message": "Quais são as principais entidades do documento?",
  "thread_id": "session-123"
}
```

> A documentação interativa completa está disponível em `http://localhost:5000/docs` enquanto o backend estiver rodando.

---

## 📖 Como Usar

1. Acesse **`http://localhost:5173`**
2. Na **página Upload**, arraste e solte arquivos PDF, CSV ou DOCX
3. Clique em **"Iniciar Extração"** para disparar o pipeline completo
4. Acompanhe o **progresso em tempo real** (P1 → P2, estágio por estágio)
5. Quando concluído, clique em **"Visualizar Grafo"**
6. Na **página Visualize**, explore o grafo com zoom, pan, filtros por tipo e busca de entidades
7. Acesse a **página Ontologia** para ver os tipos de entidade e relações descobertos
8. Use o **chat da Nadia** para fazer perguntas sobre os documentos em linguagem natural

---

## 🚨 Troubleshooting

### Backend

| Problema | Solução |
|---|---|
| `OPENAI_API_KEY not found` | Adicione sua chave em `backend/.env` |
| `Redis connection failed` | Normal — o sistema usa cache em memória automaticamente (Lite Mode) |
| `Address already in use (Errno 10048)` | Execute `taskkill /F /IM python.exe` para liberar a porta 5000 |
| `ModuleNotFoundError` | Certifique-se de ter ativado o venv e rodado `pip install -r requirements.txt` |

### Frontend

| Problema | Solução |
|---|---|
| `Cannot find module 'cytoscape'` | Execute `npm install` dentro da pasta `frontend/` |
| Requisições à API falhando | Confirme que o backend está rodando em `http://localhost:5000` |
| Página em branco na visualização | Verifique se o pipeline foi concluído com sucesso antes de abrir o grafo |

---

## 🔉 TTS Local (Kokoro-82M) — Setup Opcional

Para habilitar a voz local da Nadia:

1. Baixe os modelos `kokoro-v1.0.onnx` e `voices.bin` nos [releases do projeto Kokoro](https://github.com/nazdridoy/kokoro-onnx)
2. Coloque os arquivos dentro de `backend/`
3. Reinicie o backend

O pacote `kokoro-onnx` já está incluído no `requirements.txt`.

---

## 🧑‍💻 Desenvolvimento

### Adicionar um Novo Estágio ao Pipeline

1. Crie o arquivo em `backend/app/pipeline/stages/`
2. Implemente a classe com um método `process(context) -> context`
3. Registre o estágio em `backend/app/pipeline/orchestrator.py`

### Adicionar uma Nova Rota de API

1. Crie o arquivo em `backend/app/api/routes/`
2. Defina um `APIRouter` e os endpoints
3. Registre o router no `backend/main.py`

---

## 📄 Licença

MIT License

---

## 🙏 Créditos e Tecnologias Utilizadas

- **[OpenAI](https://openai.com)** — LLM para extração e chat
- **[LangGraph](https://www.langchain.com/langgraph)** — Orquestração do agente Nadia
- **[PyMuPDF](https://pymupdf.readthedocs.io)** — Extração de PDFs
- **[NetworkX](https://networkx.org)** — Estrutura e análise do grafo
- **[ChromaDB](https://www.trychroma.com)** — Banco vetorial semântico
- **[FAISS](https://github.com/facebookresearch/faiss)** — Indexação vetorial estrutural
- **[Cytoscape.js](https://js.cytoscape.org)** — Visualização do grafo
- **[Kokoro-ONNX](https://github.com/nazdridoy/kokoro-onnx)** — TTS local de alta qualidade
