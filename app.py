import streamlit as st
import pandas as pd
from rapidfuzz import process, fuzz
import re
from openpyxl.styles import PatternFill, Font
from io import BytesIO
from functools import lru_cache
from tqdm import tqdm
import requests

# Abbreviations mapping
JOURNAL_REPLACEMENTS = {
    'intl': 'international',
    'int': 'international',
    'natl': 'national',
    'nat': 'national',
    'sci': 'science',
    'med': 'medical',
    'res': 'research',
    'tech': 'technology',
    'eng': 'engineering',
    'phys': 'physics',
    'chem': 'chemistry',
    'bio': 'biology',
    'env': 'environmental',
    'mgmt': 'management',
    'dev': 'development',
    'edu': 'education',
    'univ': 'university',
    'j\\.': 'journal',
    'jr\\.': 'journal',
    'jrnl\\.': 'journal',
    'proc\\.': 'proceedings',
    'rev\\.': 'review',
    'q\\.': 'quarterly',
}

@lru_cache(maxsize=10000)
def standardize_text(text):
    if not isinstance(text, str):
        return ""
    text = text.lower().strip()
    text = text.replace('&', 'and')
    text = re.sub(r'[-:]', ' ', text)
    text = re.sub(r'\([^)]*?(print|online|www|web|issn|doi).*?\)', '', text, flags=re.IGNORECASE)
    for abbr, full in JOURNAL_REPLACEMENTS.items():
        text = re.sub(rf'\b{abbr}\b', full, text, flags=re.IGNORECASE)
    text = re.sub(r'[^\w\s]', ' ', text)
    return ' '.join(text.split())

def read_file(file):
    ext = file.name.split('.')[-1].lower()
    return pd.read_excel(file) if ext == 'xlsx' else pd.read_csv(file)

def process_single_file(user_df, ref_df):
    source_title_col = next((col for col in user_df.columns if 'source title' in col.lower()), None)
    if not source_title_col:
        st.error("Missing 'Source title' column.")
        return None

    journals = user_df[source_title_col].astype(str).apply(standardize_text)
    ref_df.iloc[:, 0] = ref_df.iloc[:, 0].astype(str).apply(standardize_text)

    ref_dict = {}
    for _, row in ref_df.iterrows():
        journal = row.iloc[0]
        sjr = row.iloc[1] if len(row) > 1 else "N/A"
        jif = row.iloc[2] if len(row) > 2 else "N/A"
        ref_dict.setdefault(journal, {"sjr": [], "jif": []})
        ref_dict[journal]["sjr"].append(sjr)
        ref_dict[journal]["jif"].append(jif)

    ref_journals = ref_df.iloc[:, 0].tolist()
    results = []
    for journal in tqdm(journals, desc="Processing journals"):
        if not journal.strip():
            results.append((journal, "No match found", 0, "N/A", "N/A"))
            continue
        if journal in ref_dict:
            results.append((journal, journal, 100, ', '.join(ref_dict[journal]["sjr"]), ', '.join(ref_dict[journal]["jif"])))
            continue
        match = process.extractOne(journal, ref_journals, scorer=fuzz.ratio, score_cutoff=90)
        if match:
            matched_journal = match[0]
            results.append((journal, matched_journal, match[1], ', '.join(ref_dict[matched_journal]["sjr"]), ', '.join(ref_dict[matched_journal]["jif"])))
        else:
            results.append((journal, "No match found", 0, "N/A", "N/A"))

    new_columns = ['Processed Journal Name', 'Best Match', 'Match Score', 'SJR Best Quartile', 'JIF']
    results_df = pd.DataFrame(results, columns=new_columns)

    st.write("### Matching Statistics")
    total = len(results_df)
    perfect = len(results_df[results_df['Match Score'] == 100])
    good = len(results_df[(results_df['Match Score'] >= 90) & (results_df['Match Score'] < 100)])
    no = len(results_df[results_df['Match Score'] == 0])
    st.write(f"- Total: {total}, Perfect: {perfect}, Good: {good}, No Match: {no}")

    final_df = pd.concat([user_df, results_df], axis=1).sort_values(by='Match Score')
    final_df.attrs['new_columns'] = new_columns
    return final_df

def save_results(df, file_format='xlsx'):
    output = BytesIO()
    if file_format == 'xlsx':
        writer = pd.ExcelWriter(output, engine='openpyxl')
        df.to_excel(writer, index=False)
        ws = writer.book.active
        header_fill = PatternFill(start_color='0066CC', fill_type='solid')
        sjr_fill = PatternFill(start_color='00CC66', fill_type='solid')
        jif_fill = PatternFill(start_color='FF9900', fill_type='solid')
        for cell in ws[1]:
            if cell.value == 'SJR Best Quartile':
                cell.fill = sjr_fill
            elif cell.value == 'JIF':
                cell.fill = jif_fill
            elif cell.value in df.attrs['new_columns']:
                cell.fill = header_fill
                cell.font = Font(color='FFFFFF', bold=True)
        writer.close()
    else:
        df.to_csv(output, index=False)
    output.seek(0)
    return output

# Streamlit app
st.title("📊 Journal Impact Factor and SJR Quartile Matcher")

# Load reference data from GitHub URL
try:
    reference_file_url = "https://raw.githubusercontent.com/Satyajeet1396/ifq/90057686057c21c7aaff527c1a58dfc644587fbd/ifq.xlsx"
    r = requests.get(reference_file_url)
    ref_df = pd.read_excel(BytesIO(r.content), engine='openpyxl')
    st.success(f"✅ Loaded reference database with {len(ref_df)} journals.")
except Exception as e:
    st.error(f"❌ Error loading reference database: {e}")
    st.stop()

# File upload
uploaded_files = st.file_uploader("📥 Upload Journal List Files (XLSX or CSV)", type=['xlsx', 'csv'], accept_multiple_files=True)

if 'processed_results' not in st.session_state:
    st.session_state.processed_results = {}

if uploaded_files:
    for f in uploaded_files:
        fid = f"{f.name}_{f.size}"
        if fid not in st.session_state.processed_results:
            user_df = read_file(f)
            with st.spinner(f"Processing {f.name}..."):
                results_df = process_single_file(user_df, ref_df)
                file_format = f.name.split('.')[-1].lower()
                output_file = save_results(results_df, file_format)
                st.session_state.processed_results[fid] = {
                    "df": results_df,
                    "file": output_file,
                    "name": f.name,
                    "format": file_format
                }

    st.write("## 📁 Download Processed Files")
    for fid, data in st.session_state.processed_results.items():
        name = data["name"]
        fmt = data["format"]
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if fmt == 'xlsx' else "text/csv"
        st.download_button(
            label=f"⬇️ Download {name}",
            data=data["file"],
            file_name=f"{name.rsplit('.', 1)[0]}_processed.{fmt}",
            mime=mime,
            key=f"dl_{fid}"
        )
        st.dataframe(data["df"][['Processed Journal Name', 'Best Match', 'Match Score', 'SJR Best Quartile', 'JIF']].head(10))

if st.button("🔄 Clear All"):
    st.session_state.processed_results.clear()
    st.experimental_rerun()

st.divider()
st.info("Created by Dr. Satyajeet Patil — Visit [Website](https://patilsatyajeet.wixsite.com/home/python)")
