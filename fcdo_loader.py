import pyexcel_ods3

def load_fcdo_names(path):
    data = pyexcel_ods3.get_data(path)
    # Find the first sheet
    sheet = next(iter(data.values()))
    # If sheet is empty, return empty list
    if not sheet:
        return []

    # Determine best column to use for names.
    # Prefer column index 2 (3rd column) if it has many text entries; otherwise pick column with most alphabetic values.
    max_cols = max(len(row) for row in sheet)
    col_scores = [0] * max_cols
    for row in sheet:
        for cidx in range(min(len(row), max_cols)):
            val = row[cidx]
            if val is None:
                continue
            s = str(val)
            # count as text if it contains letters
            if any(ch.isalpha() for ch in s):
                col_scores[cidx] += 1

    # prefer index 2 if it has a reasonable score
    preferred = 2 if len(col_scores) > 2 and col_scores[2] > 0 else None
    if preferred is None:
        # pick column with highest score
        best_idx = max(range(len(col_scores)), key=lambda i: col_scores[i])
    else:
        best_idx = preferred

    names = []
    for row in sheet:
        if len(row) > best_idx:
            names.append(str(row[best_idx]))
    return names
