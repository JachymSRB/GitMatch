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

# Try direct known endpoints for the UK Sanctions List export (lightweight, no headless browser)
def try_direct_fcdo_export(save_dir: Path) -> tuple:
    """Attempt to fetch the FCDO export from a list of candidate endpoints.
    Tries GET and a fallback POST. Detects filename from Content-Disposition or URL.
    Saves the file using the server-provided filename and also writes a standardized copy
    as FCDO.csv or FCDO.ods so the rest of the app can find it.
    Returns (success: bool, message: str, saved_path: Path|None)
    """
    candidates = [
        'https://search-uk-sanctions-list.service.gov.uk/search/export',
        'https://search-uk-sanctions-list.service.gov.uk/export',
        'https://search-uk-sanctions-list.service.gov.uk/search/export?format=csv',
        'https://search-uk-sanctions-list.service.gov.uk/export?format=csv',
        'https://search-uk-sanctions-list.service.gov.uk/download?format=csv'
    ]

    headers = {
        'User-Agent': 'GitMatch/1.0 (+https://github.com)',
        'Accept': '*/*'
    }

    def extract_filename(resp, url):
        cd = resp.headers.get('content-disposition') or resp.headers.get('Content-Disposition')
        if cd:
            # try filename*=UTF-8''name or filename="name"
            import re
            m = re.search(r"filename\*=[^']*'[^']*'(?P<f>[^;\n\r]+)", cd)
            if m:
                return m.group('f')
            m = re.search(r'filename="?(?P<f>[^";]+)"?', cd)
            if m:
                return m.group('f')
        # fallback to last part of URL path
        from urllib.parse import urlparse, unquote
        path = urlparse(url).path
        name = Path(unquote(path)).name
        if name:
            return name
        return None

    for url in candidates:
        # try GET
        for method in ('get', 'post'):
            try:
                if method == 'get':
                    resp = requests.get(url, headers=headers, timeout=20, allow_redirects=True)
                else:
                    # try a generic POST that some endpoints accept to trigger export
                    resp = requests.post(url, headers=headers, timeout=20, data={'format': 'csv'}, allow_redirects=True)
            except Exception:
                continue
            if not resp.ok:
                continue
            content = resp.content
            # determine filename
            fname = extract_filename(resp, resp.url)
            # simple heuristics for type
            ctype = resp.headers.get('content-type', '').lower()
            is_csv = 'csv' in ctype or 'text' in ctype or b',' in content[:1024]
            is_ods = content[:4].startswith(b'PK\x03\x04') or ctype.startswith('application/vnd.oasis') or resp.url.lower().endswith('.ods')

            if not fname:
                fname = 'fcdo_export.ods' if is_ods else 'fcdo_export.csv'

            # ensure proper extension
            ext = '.ods' if is_ods else '.csv'
            if not fname.lower().endswith(ext):
                fname = Path(fname).stem + ext

            save_path = save_dir / fname
            try:
                with open(save_path, 'wb') as f:
                    f.write(content)
            except Exception as e:
                return False, f'Failed to write file from {url}: {e}', None

            # also save a standardized copy so the rest of the app can find it
            std_name = save_dir / ('FCDO' + ext)
            try:
                with open(std_name, 'wb') as f:
                    f.write(content)
            except Exception:
                pass

            msg = f'Downloaded FCDO file from {url} and saved as {save_path.name} (also copied to {std_name.name})'
            return True, msg, save_path
    return False, 'No direct export endpoint found among candidates', None

# Determine default fallback files included with the app (if present)
# Accept 'sdn.csv' (common SDN export filename) first, then fallback to 'OFAC.csv' if present
FALLBACK_OFAC = Path('sdn.csv') if Path('sdn.csv').exists() else (Path('OFAC.csv') if Path('OFAC.csv').exists() else None)
FALLBACK_FCDO = Path('FCDO_SL_Mon_Aug 11 2025.ods') if Path('FCDO_SL_Mon_Aug 11 2025.ods').exists() else None
FALLBACK_EU = Path('20250801-FULL-1_0.csv') if Path('20250801-FULL-1_0.csv').exists() else None

# Data sources UI in a collapsed expander
with st.expander('Data sources (upload or use local files)', expanded=False):
    st.write('You can upload the sanction lists here. Uploaded files are saved to the app server and reused across runs until replaced.')
    st.markdown('- EU consolidated list: https://data.europa.eu/data/datasets/consolidated-list-of-persons-groups-and-entities-subject-to-eu-financial-sanctions?locale=en')
    st.markdown('- FCDO UK sanctions list search: https://search-uk-sanctions-list.service.gov.uk')
    st.markdown('- OFAC SDN CSV export: https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.CSV')

    uploaded_ofac = st.file_uploader('Upload OFAC CSV', type=['csv'], key='upload_ofac')
    uploaded_fcdo = st.file_uploader('Upload FCDO .ods', type=['ods', 'csv'], key='upload_fcdo')
    uploaded_eu = st.file_uploader('Upload EU CSV', type=['csv', 'txt'], key='upload_eu')

    # Save uploads to data folder if provided
    if uploaded_ofac is not None:
        target = DATA_DIR / 'OFAC.csv'
        save_uploaded_file(uploaded_ofac, target)
        st.success(f'OFAC saved to {target}')
    if uploaded_fcdo is not None:
        target = DATA_DIR / 'FCDO.ods'
        save_uploaded_file(uploaded_fcdo, target)
        st.success(f'FCDO saved to {target}')
    if uploaded_eu is not None:
        target = DATA_DIR / 'EU.csv'
        save_uploaded_file(uploaded_eu, target)
        st.success(f'EU list saved to {target}')

    # Auto-download direct attempt button
    if st.button('Try auto-download FCDO (direct endpoints)', key='auto_fcdo_direct'):
        try:
            success, msg, saved = try_direct_fcdo_export(DATA_DIR)
            if success:
                st.success(msg)
            else:
                st.warning(msg)
        except Exception as e:
            st.error(f'Auto-download failed: {e}')

    # Show currently available files (data dir or fallbacks)
    ofac_path = DATA_DIR / 'OFAC.csv' if (DATA_DIR / 'OFAC.csv').exists() else (FALLBACK_OFAC if FALLBACK_OFAC is not None else None)
    fcdo_path = DATA_DIR / 'FCDO.ods' if (DATA_DIR / 'FCDO.ods').exists() else (DATA_DIR / 'FCDO.csv' if (DATA_DIR / 'FCDO.csv').exists() else (FALLBACK_FCDO if FALLBACK_FCDO is not None else None))
    eu_path = DATA_DIR / 'EU.csv' if (DATA_DIR / 'EU.csv').exists() else (FALLBACK_EU if FALLBACK_EU is not None else None)

    st.write('Current files:')
    cols = st.columns(3)
    with cols[0]:
        st.write('OFAC:')
        if ofac_path:
            st.write(ofac_path.name)
            with open(ofac_path, 'rb') as f:
                st.download_button('Download OFAC file', f.read(), file_name=ofac_path.name, mime='text/csv')
        else:
            st.info('No OFAC file available')
    with cols[1]:
        st.write('FCDO:')
        if fcdo_path:
            st.write(fcdo_path.name)
            with open(fcdo_path, 'rb') as f:
                st.download_button('Download FCDO file', f.read(), file_name=fcdo_path.name, mime='application/vnd.oasis.opendocument.spreadsheet')
        else:
            st.info('No FCDO file available')
    with cols[2]:
        st.write('EU:')
        if eu_path:
            st.write(eu_path.name)
            with open(eu_path, 'rb') as f:
                st.download_button('Download EU file', f.read(), file_name=eu_path.name, mime='text/csv')
        else:
            st.info('No EU file available')

# Load name lists using saved files (or fallbacks)
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
