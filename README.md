# Knowledge Graph Web Platform

Uma plataforma web avançada para transformar documentos heterogêneos (PDF, CSV, DOCX) em grafos de conhecimento interativos usando extração via LLM e análise semântica profunda.

## Funcionalidades Principais

- **Nadia**: Chatbot inteligente baseado em LangGraph capaz de usar ferramentas de cálculo, exploração de grafos e busca documental.
- **GraphRAG Multimodal**: Sistema de recuperação que combina contexto estrutural (chunks) e semântico (entidades) para respostas precisas.
- **Pipeline de 2 Níveis**:
  1. **Estrutural**: Extração de texto, tabelas, figuras e seções.
  2. **Semântico**: Descoberta de entidades, normalização e mapeamento de relações complexas.
- **Visualização Interativa**: Exploração de grafos via Cytoscape.js e visualizações semânticas.
- **Local TTS (Kokoro-82M)**: Geração de voz local de alta qualidade e custo zero.
- **Dashboard Financeiro**: Acompanhamento em tempo real de custos de API e economia gerada.

## ⚡ Início Rápido (Windows)

A maneira mais fácil de rodar o projeto completo é usando o script de automação:

1. Clone o repositório.
2. Execute o comando na raiz do projeto:
   ```powershell
   .\start.bat
   ```
*O script irá configurar o ambiente virtual (venv), instalar as dependências do Back e Front, e iniciar os dois servidores automaticamente.*

## Arquitetura

### Backend (FastAPI + Python)
- **Pipelines Coordenados**:
  - **Pipeline 1 (Estrutural)**: Extração (PyMuPDF), Chunking Semântico, FAISS (Indexação vetorial).
  - **Pipeline 2 (Semântico)**: Descoberta de Ontologia, Extração de Entidades (LLM), Normalização, Grafo de Relações (NetworkX).
- **Core Nadia**:
  - **LangGraph**: Orquestração da Nadia com ferramentas (ReAct).
  - **Dual ChromaDB**: Coleções separadas para `graphrag_docs` e `graphrag_semantic`.

### Frontend (React + Vite)
  - Visualize - Interactive graph visualization
  - Ontology - Entity and relation type viewer

## Prerequisites

- Python 3.9+
- Node.js 18+
- OpenAI API key
- (Optional) Redis for caching

## Installation

### 1. Clone the Repository

```bash
cd kg-web-platform
```

### 2. Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create .env file
copy .env.example .env
# Edit .env and add your OPENAI_API_KEY

# Download TTS Models (Required for Local Voice)
# Download kokoro-v1.0.onnx and voices.bin from releases and place in backend/
```

### 3. Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Create .env file (optional)
echo "VITE_API_URL=http://localhost:5000/api/v1" > .env
```

## Running the Application

### Start Backend (Terminal 1)

```bash
cd backend
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/Mac

# Run Flask server
python wsgi.py
```

Backend will run on `http://localhost:5000`

### Start Frontend (Terminal 2)

```bash
cd frontend

# Run Vite dev server
npm run dev
```

Frontend will run on `http://localhost:5173`

## Usage

1. **Navigate to** `http://localhost:5173`
2. **Click "Upload Documents"** and drag-drop PDF/CSV/DOCX files
3. **Click "Start Knowledge Graph Extraction"** to begin processing
4. **Monitor progress** in real-time
5. **Click "View Knowledge Graph"** when complete
6. **Explore the graph** with zoom, pan, and layout controls
7. **View ontology** to see entity types and relations

## Configuration

### Environment Variables (backend/.env)

```bash
# Required
OPENAI_API_KEY=sk-your-key-here

# Optional
DATABASE_URL=sqlite:///./sql_app.db
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=your-secret-key
MAX_WORKERS=2
CACHE_TTL=604800  # 7 days
```

### Lite Mode (Low-Compute)

The system automatically falls back to "Lite Mode" when Redis is unavailable:
- Uses in-memory caching instead of Redis
- SQLite instead of PostgreSQL
- Reduced worker count (MAX_WORKERS=2)

## API Documentation

### Upload Document

```http
POST /api/v1/documents/upload
Content-Type: multipart/form-data

file: <binary>
```

### Start Pipeline

```http
POST /api/v1/pipeline/start
Content-Type: application/json

{
  "filenames": ["document.pdf"],
  "config": {}
}
```

### Get Job Status

```http
GET /api/v1/pipeline/status/{job_id}
```

### Get Graph

```http
GET /api/v1/graphs/{job_id}
```

### Get Ontology

```http
GET /api/v1/ontology/{job_id}
```

## Estrutura do Projeto

```
kg-web-platform/
├── backend/
│   ├── app/
│   │   ├── api/routes/          # Endpoints FastAPI
│   │   ├── pipeline/stages/     # Estágios do Pipeline (E1 a E5)
│   │   ├── graph/               # Gerenciadores de Grafos (Structural/Semantic)
│   │   ├── config.py            # Configurações globais
│   │   └── utils.py             # Utilitários e helpers
│   ├── requirements.txt         # Dependências sincronizadas
│   └── main.py                  # Ponto de entrada (Uvicorn)
├── frontend/
│   ├── src/
│   │   ├── pages/               # Páginas React (Upload, Visualização)
│   │   ├── components/          # Componentes (Nadia, Graph, UI)
│   │   └── api/                 # Cliente de integração
│   └── package.json
├── start.bat                    # Script de automação (Setup + Start)
└── README.md
```

## Troubleshooting

### Backend Issues

**Problem**: `ModuleNotFoundError: No module named 'docling'`
**Solution**: Ensure you've activated the virtual environment and installed requirements

**Problem**: `OpenAI API key not found`
**Solution**: Add `OPENAI_API_KEY` to `backend/.env`

**Problem**: `Redis connection failed`
**Solution**: Install Redis or let the system use in-memory fallback (Lite Mode)

### Frontend Issues

**Problem**: `Cannot find module 'cytoscape'`
**Solution**: Run `npm install` in the frontend directory

**Problem**: `API requests failing`
**Solution**: Ensure backend is running on port 5000 and CORS is configured

**Problem**: `Errno 10048 (Address already in use)`
**Solution**: A previous instance of the server is still running. Use `taskkill /F /IM python.exe` or close other terminal windows to free up port 5000.

## Development

### Adding a New Pipeline Stage

1. Create stage file in `backend/app/pipeline/stages/`
2. Implement stage class with `process()` method
3. Add stage to orchestrator in `orchestrator.py`
4. Update progress tracking

### Adding a New API Route

1. Create route file in `backend/app/api/routes/`
2. Define Blueprint and endpoints
3. Register blueprint in `app/__init__.py`

## Testing

```bash
# Backend tests
cd backend
pytest tests/

# Frontend tests
cd frontend
npm run test
```

## Deployment

### Docker (Recommended)

```bash
docker-compose up -d
```

### Manual Deployment

1. Set production environment variables
2. Build frontend: `npm run build`
3. Serve frontend static files via Flask or nginx
4. Use gunicorn for production WSGI server
5. Set up Redis for production caching

## License

MIT License

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## Support

For issues and questions, please open a GitHub issue.

## Acknowledgments

- Docling for PDF extraction
- LangChain for semantic chunking
- OpenAI for LLM capabilities
- Cytoscape.js for graph visualization
- NetworkX for graph operations
