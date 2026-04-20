"""PDF parser — extracts text with PyMuPDF and tables with pdfplumber."""

import fitz
import pdfplumber


def pdfParser(file_path):
    """Extract text, tables, and page/table counts from a PDF file."""
    doc = fitz.open(file_path)
    text = ""
    for page in doc:
        text += page.get_text()
    num_pages = len(doc)
    doc.close()

    tables = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            page_tables = page.extract_tables()
            if page_tables:
                tables.extend(page_tables)

    metadata = {
        "num_pages": num_pages,
        "num_tables": len(tables)
    }

    return {
        "text": text,
        "tables": tables,
        "metadata": metadata
    }