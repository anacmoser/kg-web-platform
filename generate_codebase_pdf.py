import os
import sys

# Try to import fpdf, check if installed
try:
    from fpdf import FPDF
except ImportError:
    print("Error: 'fpdf2' library is not installed.")
    print("Please install it by running: pip install fpdf2")
    sys.exit(1)

class PDF(FPDF):
    def header(self):
        self.set_font('Courier', 'B', 10)
        self.cell(0, 5, 'KG Web Platform Codebase', 0, 1, 'C')
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font('Courier', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')

def generate_pdf(root_dir, output_file):
    pdf = PDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Courier", size=8)

    # Directories to exclude
    excluded_dirs = {
        'node_modules', '.git', '__pycache__', 'venv', 'dist', 'build', 
        '.idea', '.vscode', 'coverage', '.pytest_cache', 'site-packages', 'brain'
    }
    
    # Files to exclude (binaries, locks, etc.)
    excluded_files = {
        'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml', 'poetry.lock',
        '.DS_Store', 'Thumbs.db', '.env', 'generate_codebase_pdf.py',
        'playwright-report', 'test-results', '.gitignore', '.gitattributes'
    }
    
    # Extensions to exclude
    excluded_exts = (
        '.pyc', '.pyo', '.pyd', '.so', '.dll', '.exe', '.bin', 
        '.png', '.jpg', '.jpeg', '.gif', '.ico', '.pdf', '.zip', 
        '.tar.gz', '.woff', '.woff2', '.ttf', '.eot', '.mp4', 
        '.webm', '.mp3', '.wav', '.sqlite', '.db'
    )

    print(f"Scanning directory: {root_dir}")
    
    for root, dirs, files in os.walk(root_dir):
        # Filter directories inplace
        dirs[:] = [d for d in dirs if d not in excluded_dirs]
        dirs.sort() # Ensure consistent order
        
        # Sort files for consistent order
        for file in sorted(files):
            if file in excluded_files:
                continue
            if file.endswith(excluded_exts):
                continue
                
            file_path = os.path.join(root, file)
            rel_path = os.path.relpath(file_path, root_dir)
            
            # Skip if file is too large (> 1MB) to avoid memory issues
            if os.path.getsize(file_path) > 1024 * 1024:
                print(f"Skipping large file: {rel_path}")
                continue

            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            except UnicodeDecodeError:
                print(f"Skipping binary or non-utf8 file: {rel_path}")
                continue
            except Exception as e:
                print(f"Error reading {rel_path}: {e}")
                continue

            # Add file header to PDF
            pdf.set_font("Courier", 'B', 12)
            pdf.set_text_color(0, 0, 128) # Navy blue for filenames
            
            # Check if we need a page break soon
            if pdf.get_y() > 250:
                pdf.add_page()
                
            pdf.cell(0, 10, f"File: {rel_path}", 0, 1)
            pdf.set_text_color(0, 0, 0)
            pdf.set_font("Courier", size=8)
            
            # Add content
            # multi_cell is good for wrapping long lines
            # encode to latin-1 for fpdf (standard) or handle unicode
            # fpdf2 handles unicode if font supports it, but standard fonts (Courier) only support latin-1
            # We will use explicit encoding handling to avoid crashes
            
            try:
                # Replace unsupported characters or encode
                safe_content = content.encode('latin-1', 'replace').decode('latin-1')
                pdf.multi_cell(0, 4, safe_content)
            except Exception as e:
                print(f"  Warning: formatting issue in {rel_path}: {e}")
                pdf.multi_cell(0, 4, "[Content could not be rendered due to encoding issues]")
                
            pdf.ln(5) # Space after file
            print(f"Added: {rel_path}")

    try:
        pdf.output(output_file)
        print(f"\nPDF generated successfully: {output_file}")
    except Exception as e:
        print(f"Error saving PDF: {e}")

if __name__ == "__main__":
    # Get the directory where the script is located
    current_dir = os.path.dirname(os.path.abspath(__file__))
    output_path = os.path.join(current_dir, 'kg_web_platform_codebase.pdf')
    generate_pdf(current_dir, output_path)
