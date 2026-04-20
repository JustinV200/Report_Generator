"""Excel parser — reads all sheets into text and table representations."""

import pandas as pd


def excelParser(file_path):
    """Parse an Excel file and return combined text, per-sheet tables, and metadata."""
    sheets = pd.read_excel(file_path, sheet_name=None)  # dict of {sheet_name: DataFrame}
    text = ""
    tables = []
    for name, df in sheets.items():
        text += f"\n--- {name} ---\n{df.to_string(index=False)}"
        tables.append({"sheet": name, "data": df.to_dict(orient="records")})

    metadata = {
        "num_sheets": len(sheets),
        "sheets": [
            {"name": name, "num_rows": len(df), "num_columns": len(df.columns), "columns": list(df.columns)}
            for name, df in sheets.items()
        ]
    }
    return {
        "text": text,
        "tables": tables,
        "metadata": metadata
    }