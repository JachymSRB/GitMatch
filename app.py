import streamlit as st
import pandas as pd
import re
from rapidfuzz import process, fuzz
from fcdo_loader import load_fcdo_names
from eu_loader import load_eu_names

# Load OFAC data
@st.cache_data
def load_ofac():
    df = pd.read_csv('OFAC.csv', header=None)
    # 4th column is index 3
    names = df.iloc[:, 3].astype(str).tolist()
    return names



ofac_names = load_ofac()
fcdo_names = load_fcdo_names('FCDO_SL_Mon_Aug 11 2025.ods')
eu_names = load_eu_names('20250801-FULL-1_0.csv')

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
st.title('Pazdrát Fuzzy Matcher')
st.write('Paste a column of names from Excel below:')
threshold = st.slider('Minimum match score threshold', min_value=0, max_value=100, value=70, key='threshold_slider')


# Layout: input 1 wide, output 3 wide


# Editable input table in expander
with st.expander('Input Table', expanded=False):
    input_df = st.data_editor(pd.DataFrame({'Names': ['']}), num_rows="dynamic", use_container_width=True)

# Results table below title and above input
if not input_df.empty and input_df['Names'].str.strip().any():
    ofac_result = []
    fcdo_result = []
    eu_result = []
    for name in input_df['Names'].dropna():
        # OFAC matches
        ofac_matches = get_top_matches(name, ofac_names)
        ofac_filtered = [m for m in ofac_matches if m[1] >= threshold]
        if ofac_filtered:
            ofac_str = ', '.join([f"{m[0]} ({m[1]})" for m in ofac_filtered])
        else:
            ofac_str = ''
        ofac_result.append(ofac_str)
        # FCDO matches
        fcdo_matches = get_top_matches(name, fcdo_names)
        fcdo_filtered = [m for m in fcdo_matches if m[1] >= threshold]
        if fcdo_filtered:
            fcdo_str = ', '.join([f"{m[0]} ({m[1]})" for m in fcdo_filtered])
        else:
            fcdo_str = ''
        fcdo_result.append(fcdo_str)
        # EU matches
        eu_matches = get_top_matches(name, eu_names)
        eu_filtered = [m for m in eu_matches if m[1] >= threshold]
        if eu_filtered:
            eu_str = ', '.join([f"{m[0]} ({m[1]})" for m in eu_filtered])
        else:
            eu_str = ''
        eu_result.append(eu_str)
    output_df = pd.DataFrame({'Names': input_df['Names'], 'OFAC Matches': ofac_result, 'FCDO Matches': fcdo_result, 'EU Matches': eu_result})
    st.dataframe(output_df, use_container_width=True, hide_index=True)
else:
    st.info('Enter names to see matches.')
