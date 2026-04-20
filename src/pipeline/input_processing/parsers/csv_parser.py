"""CSV parser — reads a CSV into a DataFrame and returns text + table representations."""

import pandas as pd


def csvParser(file_path, encoding="utf-8"):
    """Parse a CSV file and return text, table records, and column metadata."""
    df = pd.read_csv(file_path, encoding=encoding)
    text = df.to_string(index=False)
    tables = [df.to_dict(orient="records")]
    metadata = {
        "num_rows": len(df),
        "num_columns": len(df.columns),
        "columns": list(df.columns)
    }
    return {
        "text": text,
        "tables": tables,
        "metadata": metadata
    }