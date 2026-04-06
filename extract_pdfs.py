import os, glob, fitz
pdf_dir = "/Users/daniel/Documents/GitHub/PCRS-scraper/CSC209"
output_file = "/Users/daniel/Documents/GitHub/PCRS-scraper/CSC209_compiled.md"
def get_sort_key(filename):
    basename = os.path.basename(filename)
    if basename.startswith("lecture"):
        try: return (0, int(basename.replace("lecture", "").replace(".pdf", "")))
        except ValueError: return (0, 999)
    return (1, basename)
pdf_files = glob.glob(os.path.join(pdf_dir, "*.pdf"))
pdf_files.sort(key=get_sort_key)
with open(output_file, "w", encoding="utf-8") as out:
    out.write("# CSC209 Compiled PDFs\n\n")
    for pdf_path in pdf_files:
        filename = os.path.basename(pdf_path)
        out.write(f"## {filename}\n\n")
        try:
            doc = fitz.open(pdf_path)
            for page in doc:
                text = page.get_text()
                if text.strip():
                    out.write(text + "\n")
            out.write("\n---\n\n")
            doc.close()
            print(f"Processed {filename}")
        except Exception as e:
            print(f"Error {filename}: {e}")
print(f"All PDFs compiled successfully into {output_file}")
