import sys
import os

# Add backend to path
sys.path.append(os.path.join(os.getcwd(), 'backend'))

print(f"CWD: {os.getcwd()}")
print("Verifying imports...")

try:
    import flask
    print("Flask ok")
    import openai
    print("OpenAI ok")
    import fitz
    print("PyMuPDF (fitz) ok")
    import rapidfuzz
    print("RapidFuzz ok")
    import networkx
    print("NetworkX ok")
    
    # Check app imports
    from app.config import settings
    print(f"App Config ok. Env: {settings.PROJECT_NAME}")
    from app.pipeline.orchestrator import orchestrator
    print("Orchestrator ok")
    
    print("All checks passed.")
except ImportError as e:
    print(f"Import Error: {e}")
except Exception as e:
    print(f"Error: {e}")
