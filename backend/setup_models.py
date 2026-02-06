import spacy
import sys

def setup():
    model_name = "en_core_web_sm"
    print(f"Checking for spaCy model: {model_name}...")
    try:
        spacy.load(model_name)
        print(f"OK: Model {model_name} already installed.")
    except OSError:
        print(f"Downloading spaCy model {model_name}...")
        try:
            spacy.cli.download(model_name)
            print(f"OK: Model {model_name} installed successfully.")
        except Exception as e:
            print(f"❌ Failed to download model: {e}")
            sys.exit(1)

if __name__ == "__main__":
    setup()
