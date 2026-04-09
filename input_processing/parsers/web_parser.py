import trafilatura

def webParser(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        raw_html = f.read()
    text = trafilatura.extract(raw_html)
    metadata = trafilatura.bare_extraction(raw_html)
    
    if metadata:
        meta_dict = {
            "title": getattr(metadata, "title", "") or "",
            "author": getattr(metadata, "author", "") or "",
            "date": getattr(metadata, "date", "") or "",
            "sitename": getattr(metadata, "sitename", "") or "",
        }
    else:
        meta_dict = {}

    return {
        "text": text,
        "tables": [],
        "metadata": meta_dict
    }