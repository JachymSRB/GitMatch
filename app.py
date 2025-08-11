import streamlit as st
import pandas as pd
import re
from rapidfuzz import process, fuzz

# Load OFAC data
@st.cache_data
def load_ofac():
    df = pd.read_csv('OFAC.csv', header=None)
    # 4th column is index 3
    names = df.iloc[:, 3].astype(str).tolist()
    return names

ofac_names = load_ofac()

def normalize(text):
    # Remove special characters, lowercase, and tokenize
    text = re.sub(r'[^\w\s]', '', text)
    tokens = text.lower().split()
    return ' '.join(tokens)

def get_top_matches(query, choices, n=3):
    query_norm = normalize(query)
    choices_norm = [normalize(c) for c in choices]
    results = process.extract(query_norm, choices_norm, scorer=fuzz.token_sort_ratio, limit=n)
    # Map back to original names and show rounded score
    return [(choices[i], int(round(score))) for (_, score, i) in results]



st.set_page_config(layout="wide")

# Title and sensitivity slider across the top
st.title('OFAC Fuzzy Matcher')
st.write('Paste a column of names from Excel below:')
threshold = st.slider('Minimum match score threshold', min_value=0, max_value=100, value=70, key='threshold_slider')


# Layout: input 1 wide, output 3 wide
col1, col2 = st.columns([1, 3])

with col1:
    input_df = st.data_editor(pd.DataFrame({'Names': ['']}), num_rows="dynamic", use_container_width=True)

with col2:
    if not input_df.empty and input_df['Names'].str.strip().any():
        result = []
        for name in input_df['Names'].dropna():
            matches = get_top_matches(name, ofac_names)
            # Filter matches by threshold
            filtered = [m for m in matches if m[1] >= threshold]
            if filtered:
                match_str = ', '.join([f"{m[0]} ({m[1]})" for m in filtered])
            else:
                match_str = ''
            result.append(match_str)
        output_df = pd.DataFrame({'Top Matches': result})
        st.table(output_df)
    else:
        st.info('Enter names to see matches.')
