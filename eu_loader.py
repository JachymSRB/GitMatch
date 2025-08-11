import pandas as pd

def load_eu_names(path):
    df = pd.read_csv(path, sep=';', header=0)
    # Column R is index 17, named 'Naal_wholename'
    names = df['Naal_wholename'].dropna().astype(str).tolist()
    return names
