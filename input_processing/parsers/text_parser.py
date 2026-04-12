"""Plain-text parser — reads a text file and returns it as-is."""


def textParser(file_path, encoding="utf-8"):
    """Read *file_path* as plain text and return a parsed-data dict."""
    with open(file_path, 'r', encoding=encoding) as file:
        text = file.read()
    return {
        "text": text,
        "tables": [],
        "metadata": {}
    }