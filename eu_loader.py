import pandas as pd

def load_eu_names(path):
    # EU CSVs are typically semicolon-separated with a header. Be permissive.
    try:
        df = pd.read_csv(path, sep=';', header=0, dtype=str, engine='python')
    except Exception:
        df = pd.read_csv(path, sep=';', header=None, dtype=str, engine='python')

    cols = list(df.columns)
    col_low = [str(c).lower() for c in cols]

    # Prefer exact 'NameAlias_WholeName' (case-insensitive) or close variants
    for i, c in enumerate(col_low):
        clean = c.replace('.', '_').replace(' ', '_')
        if clean == 'namealias_wholename' or clean == 'namealiaswhole_name' or clean == 'namealiaswhole' or clean == 'namealias_whole':
            return df[cols[i]].dropna().astype(str).tolist()

    # Accept columns that contain both 'namealias' and 'whole' (robust to separators)
    for i, c in enumerate(col_low):
        if 'namealias' in c and 'whole' in c:
            return df[cols[i]].dropna().astype(str).tolist()

    # Then accept any column that looks like a whole-name column
    for i, c in enumerate(col_low):
        if 'wholename' in c or ('whole' in c and 'name' in c):
            return df[cols[i]].dropna().astype(str).tolist()

    # Next, pick any column containing the substring 'name'
    for i, c in enumerate(col_low):
        if 'name' in c:
            return df[cols[i]].dropna().astype(str).tolist()

    # If the file matches older expectations, try index 17 (column R)
    if len(cols) > 17:
        return df[cols[17]].dropna().astype(str).tolist()

    # Final fallback: choose the most text-heavy column (most alphabetic entries)
    best = None
    for c in cols:
        score = df[c].astype(str).str.match(r'.*[A-Za-z].*').sum()
        if best is None or score > best[1]:
            best = (c, score)
    return df[best[0]].dropna().astype(str).tolist()
