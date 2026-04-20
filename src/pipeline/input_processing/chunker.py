"""Chunker — splits parsed document text and tables into overlapping chunks for extraction."""

import json


def chunker(parsed_data, chunk_size=1000, overlap=150):
    """Split parsed text into word-limited chunks with overlap; tables become separate chunks."""
    text = parsed_data.get("text", "")
    tables = parsed_data.get("tables", [])
    metadata = parsed_data.get("metadata", {})

    chunks = []
    chunk_index = 0

    # Split text on paragraphs, then accumulate into chunks
    # Try \n\n first, fall back to \n if text has no double breaks
    if "\n\n" in text:
        paragraphs = text.split("\n\n")
    elif "\n" in text:
        paragraphs = text.split("\n")
    else:
        # No line breaks at all — hard split by words
        words = text.split()
        paragraphs = [" ".join(words[i:i+chunk_size]) for i in range(0, len(words), chunk_size)]

    current_chunk = ""

    for para in paragraphs:
        # Hard split any single paragraph that exceeds chunk_size on its own
        para_words = para.split()
        if len(para_words) > chunk_size:
            # Flush current chunk first
            if current_chunk.strip():
                chunks.append({
                    "chunk_index": chunk_index,
                    "chunk_type": "text",
                    "content": current_chunk.strip(),
                    "metadata": metadata
                })
                chunk_index += 1
                current_chunk = ""
            # Split the oversized paragraph into pieces
            for i in range(0, len(para_words), chunk_size - overlap):
                piece = " ".join(para_words[i:i+chunk_size])
                chunks.append({
                    "chunk_index": chunk_index,
                    "chunk_type": "text",
                    "content": piece,
                    "metadata": metadata
                })
                chunk_index += 1
            continue

        # if adding this paragraph would exceed chunk size, emit current chunk
        if len(current_chunk.split()) + len(para_words) > chunk_size and current_chunk:
            chunks.append({
                "chunk_index": chunk_index,
                "chunk_type": "text",
                "content": current_chunk.strip(),
                "metadata": metadata
            })
            chunk_index += 1
            # overlap: keep the last ~overlap words
            words = current_chunk.split()
            current_chunk = " ".join(words[-overlap:]) + "\n\n"

        current_chunk += para + "\n\n"

    #last chunk
    if current_chunk.strip():
        chunks.append({
            "chunk_index": chunk_index,
            "chunk_type": "text",
            "content": current_chunk.strip(),
            "metadata": metadata
        })
        chunk_index += 1

    # each table is its own chunk
    for table in tables:
        table_str = json.dumps(table) if not isinstance(table, str) else table
        table_words = table_str.split()
        if len(table_words) > chunk_size:
            for i in range(0, len(table_words), chunk_size):
                chunks.append({
                    "chunk_index": chunk_index,
                    "chunk_type": "table",
                    "content": " ".join(table_words[i:i + chunk_size]),
                    "metadata": metadata
                })
                chunk_index += 1
        else:
            chunks.append({
                "chunk_index": chunk_index,
                "chunk_type": "table",
                "content": table,
                "metadata": metadata
            })
            chunk_index += 1

    return chunks