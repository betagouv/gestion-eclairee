import re

from unidecode import unidecode

import pandas as pd


def clean_column_name(col: str) -> str:
    """Clean a column name to be SQL-compatible.

    First converts accented characters to ASCII using unidecode,
    then replaces special characters with underscores, removes multiple/leading/trailing
    underscores, and converts to lowercase.

    Args:
        col: Original column name

    Returns:
        SQL-compatible column name
    """
    # Convert accented characters to ASCII first (e.g., é -> e, ç -> c)
    col = unidecode(col)
    # Replace any non-alphanumeric/underscore character with underscore
    col = re.sub(r"[^a-zA-Z0-9_]", "_", col)
    # Remove multiple consecutive underscores
    col = re.sub(r"_+", "_", col)
    # Remove leading and trailing underscores
    col = col.strip("_")
    # Convert to lowercase
    col = col.lower()
    return col


def clean_dataframe_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Clean all column names in a DataFrame to be SQL-compatible.

    Args:
        df: DataFrame with original column names

    Returns:
        DataFrame with cleaned column names
    """
    df.columns = [clean_column_name(col) for col in df.columns]
    return df
