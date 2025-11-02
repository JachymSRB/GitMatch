import streamlit as st
import pandas as pd
import re
import unicodedata
from rapidfuzz import process, fuzz
from fcdo_loader import load_fcdo_names
from eu_loader import load_eu_names
import os
from pathlib import Path
import requests

DATA_DIR = Path('data')
DATA_DIR.mkdir(exist_ok=True)

# Helpers to save uploads
def save_uploaded_file(uploaded, target_path: Path):
    if uploaded is None:
        return None
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with open(target_path, 'wb') as f:
        f.write(uploaded.getbuffer())
    return target_path

# Cached loaders that read from a file path. Cache keyed by path so updates reload.
@st.cache_data
def load_ofac_from(path: str):
    df = pd.read_csv(path, header=None)
    names = df.iloc[:, 3].astype(str).tolist()
    return names

@st.cache_data
def load_fcdo_from(path: str):
    # reuse existing loader if available (fcdo_loader.load_fcdo_names expects a path)
    return load_fcdo_names(path)

@st.cache_data
def load_eu_from(path: str):
    return load_eu_names(path)

# Data sources UI (upload only) — remove autodownloads and fallbacks; rely only on user uploads
with st.expander('Data sources (upload only)', expanded=False):
    st.write('Upload the sanction lists below. Uploaded files are saved to the app server and reused across runs until replaced.')
    st.markdown('- EU consolidated list: https://data.europa.eu/data/datasets/consolidated-list-of-persons-groups-and-entities-subject-to-eu-financial-sanctions?locale=en')
    st.markdown('- FCDO UK sanctions list search: https://search-uk-sanctions-list.service.gov.uk')
    st.markdown('- OFAC SDN CSV export: https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.CSV')

    uploaded_ofac = st.file_uploader('Upload OFAC CSV', type=['csv'], key='upload_ofac')
    uploaded_fcdo = st.file_uploader('Upload FCDO (.ods or .csv)', type=['ods', 'csv'], key='upload_fcdo')
    uploaded_eu = st.file_uploader('Upload EU CSV', type=['csv', 'txt'], key='upload_eu')

    # Save uploads to data folder if provided
    if uploaded_ofac is not None:
        target = DATA_DIR / 'OFAC.csv'
        save_uploaded_file(uploaded_ofac, target)
        st.success(f'OFAC saved to {target}')
    if uploaded_fcdo is not None:
        # preserve extension if user uploaded csv
        ext = Path(uploaded_fcdo.name).suffix.lower() if uploaded_fcdo.name else '.ods'
        if ext not in ('.ods', '.csv'):
            ext = '.ods'
        target = DATA_DIR / ('FCDO' + ext)
        save_uploaded_file(uploaded_fcdo, target)
        st.success(f'FCDO saved to {target}')
    if uploaded_eu is not None:
        target = DATA_DIR / 'EU.csv'
        save_uploaded_file(uploaded_eu, target)
        st.success(f'EU list saved to {target}')

    # Show currently uploaded files from data/ only
    st.write('Currently uploaded files:')
    cols = st.columns(3)
    ofac_path = DATA_DIR / 'OFAC.csv' if (DATA_DIR / 'OFAC.csv').exists() else None
    fcdo_path = None
    if (DATA_DIR / 'FCDO.ods').exists():
        fcdo_path = DATA_DIR / 'FCDO.ods'
    elif (DATA_DIR / 'FCDO.csv').exists():
        fcdo_path = DATA_DIR / 'FCDO.csv'
    eu_path = DATA_DIR / 'EU.csv' if (DATA_DIR / 'EU.csv').exists() else None

    with cols[0]:
        st.write('OFAC:')
        if ofac_path:
            st.write(ofac_path.name)
            with open(ofac_path, 'rb') as f:
                st.download_button('Download OFAC file', f.read(), file_name=ofac_path.name, mime='text/csv')
        else:
            st.info('No OFAC file uploaded')
    with cols[1]:
        st.write('FCDO:')
        if fcdo_path:
            st.write(fcdo_path.name)
            # FCDO download button removed: users must upload the file and it will be used by the app
        else:
            st.info('No FCDO file uploaded')
    with cols[2]:
        st.write('EU:')
        if eu_path:
            st.write(eu_path.name)
            with open(eu_path, 'rb') as f:
                st.download_button('Download EU file', f.read(), file_name=eu_path.name, mime='text/csv')
        else:
            st.info('No EU file uploaded')

# Load name lists using only uploaded files in data/ (no fallbacks)
ofac_names = []
fcdo_names = []
eu_names = []
if ofac_path:
    ofac_names = load_ofac_from(str(ofac_path))
if fcdo_path:
    fcdo_names = load_fcdo_from(str(fcdo_path))
if eu_path:
    eu_names = load_eu_from(str(eu_path))

# Normalization utilities
def normalize(text: str) -> str:
    if not text:
        return ''
    text = str(text)
    # Unicode normalize, remove diacritics
    text = unicodedata.normalize('NFKD', text)
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))
    # Lowercase and remove non-alphanumeric (keep spaces)
    text = text.lower()
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def ngrams(s: str, n: int = 3) -> set:
    # simple character n-grams with boundary markers
    if not s:
        return set()
    s2 = '_' + re.sub(r'\s+', ' ', s) + '_'
    return {s2[i:i+n] for i in range(len(s2) - n + 1)}


def jaccard_grams(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# preserve existing enhancement logic (remove vich/vna tokens etc.)
def enhance_names(names):
    enhanced = set(names)
    for name in names:
        tokens = str(name).split()
        filtered = [t for t in tokens if not ("vich" in t or "vna" in t)]
        if len(filtered) < len(tokens):
            new_name = " ".join(filtered)
            if new_name:
                enhanced.add(new_name)
    return list(enhanced)


@st.cache_resource
def get_enhanced_lists(ngram_n: int = 3):
    """Return enhanced name lists and precomputed normalized forms and n-grams.
    Each list element is a dict: {'orig': original_name, 'norm': normalized, 'grams': set, 'len': int}
    """
    ofac = enhance_names(ofac_names)
    fcdo = enhance_names(fcdo_names)
    eu = enhance_names(eu_names)

    def enrich_list(lst, n):
        out = []
        for name in lst:
            norm = normalize(name)
            out.append({'orig': name, 'norm': norm, 'grams': ngrams(norm, n), 'len': len(norm)})
        return out

    return enrich_list(ofac, ngram_n), enrich_list(fcdo, ngram_n), enrich_list(eu, ngram_n)


def candidate_filter(query_norm: str, qgrams: set, qlen: int, choices_struct: list,
                     jaccard_thresh: float = 0.18, length_frac: float = 0.5,
                     require_first_letter: bool = False) -> list:
    """Return subset of choices_struct that pass cheap filters."""
    candidates = []
    q_first = query_norm[0] if query_norm else ''
    for item in choices_struct:
        # length fractional difference filter
        if qlen == 0 and item['len'] == 0:
            pass
        else:
            if max(qlen, 1) > 0 and abs(qlen - item['len']) / max(qlen, 1) > length_frac:
                continue
        # optional first-letter block
        if require_first_letter and q_first and item['norm'] and item['norm'][0] != q_first:
            continue
        # jaccard n-gram filter
        if jaccard_grams(qgrams, item['grams']) < jaccard_thresh:
            continue
        candidates.append(item)
    return candidates


def get_top_matches(query, choices_struct, n=3, jaccard_thresh=0.18, length_frac=0.5, score_cutoff=60, require_first_letter=False):
    # Enhance input name if it contains 'vich' or 'vna'
    tokens = str(query).split()
    filtered = [t for t in tokens if not ("vich" in t or "vna" in t)]
    queries = [str(query)]
    if len(filtered) < len(tokens):
        new_query = " ".join(filtered)
        if new_query:
            queries.append(new_query)

    all_matches = []
    for q in queries:
        query_norm = normalize(q)
        qlen = len(query_norm)
        # qgrams should be computed with the same n that was used for precomputing choices
        # default n value in ngrams() is 3; choices_struct will have grams computed accordingly
        # infer n from one candidate if present
        if choices_struct and 'grams' in choices_struct[0] and choices_struct[0]['grams']:
            # try to infer n from one gram length (not exact but works for common n)
            sample = next(iter(choices_struct[0]['grams']))
            qgrams = ngrams(query_norm, len(sample))
        else:
            qgrams = ngrams(query_norm)

        # cheap pre-filter to reduce candidates
        candidates = candidate_filter(query_norm, qgrams, qlen, choices_struct,
                                      jaccard_thresh=jaccard_thresh, length_frac=length_frac,
                                      require_first_letter=require_first_letter)
        if not candidates:
            continue
        # prepare lists for rapidfuzz (norms) and keep mapping to original
        choices_norm = [c['norm'] for c in candidates]
        orig_names = [c['orig'] for c in candidates]
        # Use RapidFuzz to get top matches among filtered candidates
        # Set processor=None because we already normalized the strings; use score_cutoff for early exit
        results = process.extract(query_norm, choices_norm, scorer=fuzz.token_sort_ratio,
                                  processor=None, score_cutoff=score_cutoff, limit=n)
        # Map back to original names and collect
        for (choice_norm, score, idx) in results:
            all_matches.append((orig_names[idx], int(round(score))))

    # Deduplicate by name, keep highest score, and sort
    match_dict = {}
    for name, score in all_matches:
        if name not in match_dict or score > match_dict[name]:
            match_dict[name] = score
    sorted_matches = sorted(match_dict.items(), key=lambda x: x[1], reverse=True)
    return sorted_matches[:n]


st.set_page_config(layout="wide")

# Title and sensitivity slider across the top
st.title('Pazdrát Fuzzy Matcher')
st.write('Paste a column of names from Excel below:')
threshold = st.slider('Minimum match score threshold', min_value=0, max_value=100, value=70, key='threshold_slider')

# Advanced controls in a collapsed expander
adv_defaults = {
    'jaccard_thresh': 0.18,
    'length_frac': 0.5,
    'score_cutoff': None,  # will default to threshold if None
    'ngram_n': 3,
    'require_first_letter': False,
    'top_n': 3
}

with st.expander('Advanced', expanded=False):
    # use prefixed keys so they don't collide with other widgets
    st.slider('Jaccard n-gram threshold', min_value=0.0, max_value=1.0, value=adv_defaults['jaccard_thresh'], step=0.01, key='adv_jaccard_thresh')
    st.slider('Max relative length difference', min_value=0.0, max_value=1.0, value=adv_defaults['length_frac'], step=0.01, key='adv_length_frac')
    st.slider('RapidFuzz score cutoff (early exit)', min_value=0, max_value=100, value=threshold, key='adv_score_cutoff')
    st.slider('N-gram size (for blocking)', min_value=2, max_value=5, value=adv_defaults['ngram_n'], step=1, key='adv_ngram_n')
    st.checkbox('Require same first letter', value=adv_defaults['require_first_letter'], key='adv_require_first_letter')
    st.number_input('Results per list', min_value=1, max_value=10, value=adv_defaults['top_n'], step=1, key='adv_top_n')

# Read advanced settings (use defaults if widget not rendered yet)
jaccard_thresh = st.session_state.get('adv_jaccard_thresh', adv_defaults['jaccard_thresh'])
length_frac = st.session_state.get('adv_length_frac', adv_defaults['length_frac'])
score_cutoff = st.session_state.get('adv_score_cutoff', threshold if adv_defaults['score_cutoff'] is None else adv_defaults['score_cutoff'])
ngram_n = st.session_state.get('adv_ngram_n', adv_defaults['ngram_n'])
require_first_letter = st.session_state.get('adv_require_first_letter', adv_defaults['require_first_letter'])
top_n = st.session_state.get('adv_top_n', adv_defaults['top_n'])

# Editable input table in expander
with st.expander('Input Table', expanded=False):
    input_df = st.data_editor(pd.DataFrame({'Names': ['']}), num_rows="dynamic", use_container_width=True)

# Results table below title and above input
if not input_df.empty and input_df['Names'].str.strip().any():
    # get precomputed enhanced lists for the selected n-gram size
    ofac_enh, fcdo_enh, eu_enh = get_enhanced_lists(ngram_n)
    ofac_result = []
    fcdo_result = []
    eu_result = []
    for name in input_df['Names'].dropna():
        # OFAC matches
        ofac_matches = get_top_matches(name, ofac_enh, n=top_n, jaccard_thresh=jaccard_thresh, length_frac=length_frac, score_cutoff=score_cutoff, require_first_letter=require_first_letter)
        ofac_filtered = [m for m in ofac_matches if m[1] >= threshold]
        if ofac_filtered:
            ofac_str = ', '.join([f"{m[0]} ({m[1]})" for m in ofac_filtered])
        else:
            ofac_str = ''
        ofac_result.append(ofac_str)
        # FCDO matches
        fcdo_matches = get_top_matches(name, fcdo_enh, n=top_n, jaccard_thresh=jaccard_thresh, length_frac=length_frac, score_cutoff=score_cutoff, require_first_letter=require_first_letter)
        fcdo_filtered = [m for m in fcdo_matches if m[1] >= threshold]
        if fcdo_filtered:
            fcdo_str = ', '.join([f"{m[0]} ({m[1]})" for m in fcdo_filtered])
        else:
            fcdo_str = ''
        fcdo_result.append(fcdo_str)
        # EU matches
        eu_matches = get_top_matches(name, eu_enh, n=top_n, jaccard_thresh=jaccard_thresh, length_frac=length_frac, score_cutoff=score_cutoff, require_first_letter=require_first_letter)
        eu_filtered = [m for m in eu_matches if m[1] >= threshold]
        if eu_filtered:
            eu_str = ', '.join([f"{m[0]} ({m[1]})" for m in eu_filtered])
        else:
            eu_str = ''
        eu_result.append(eu_str)
    output_df = pd.DataFrame({'Names': input_df['Names'], 'OFAC Matches': ofac_result, 'FCDO Matches': fcdo_result, 'EU Matches': eu_result})
    st.dataframe(output_df, use_container_width=True, hide_index=True)

    # Add download button for the output CSV
    csv = output_df.to_csv(index=False).encode('utf-8')
    st.download_button(label='Download results as CSV', data=csv, file_name='matches.csv', mime='text/csv')
else:
    st.info('Enter names to see matches.')
