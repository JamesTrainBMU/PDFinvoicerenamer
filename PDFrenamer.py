import streamlit as st
import re
import pdfplumber
from io import BytesIO
import zipfile
import os
from typing import Optional, Tuple

# -------------------------------
# Extraction helpers
# -------------------------------

def _normalise_text(text: str) -> str:
    # Collapse multiple spaces/newlines to make regexes more reliable
    return re.sub(r"[ \t]+", " ", re.sub(r"\r?\n+", "\n", text)).strip()

def _safe_filename(name: str) -> str:
    # Remove filesystem-unsafe chars and trim
    name = re.sub(r'[\\/:*?"<>|]+', "_", name).strip().strip(".")
    return name or "unnamed"

def _detect_supplier(text: str) -> Optional[str]:
    t = text.lower()
    if "corona energy" in t:
        return "CoronaEnergy"
    if "pozitive" in t:
        return "PozitiveEnergy"
    if "octopus energy" in t:
        return "OctopusEnergy"
    if "ovo energy" in t or "ovo electricity" in t:
        return "OVOEnergy"
    if "sse" in t and "energy" in t:
        return "SSE"
    return None

# ------------ NEW: extract both AGR and invoice ------------
def extract_ids_from_text(text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Returns (invoice_ref, agr_ref) in UPPERCASE if found.
    Accepts IV/IN/CN as invoice refs. Handles hyphenated forms.
    """

    # 0) Hyphenated patterns in either order; normalise to consistent pieces
    m = re.search(r"\b((?:IV|IN|CN)\d{5,})\s*[-–]\s*(AGR\d{4,})\b", text, re.IGNORECASE)
    if m:
        inv, agr = m.group(1).upper(), m.group(2).upper()
        return inv, agr

    m = re.search(r"\b(AGR\d{4,})\s*[-–]\s*((?:IV|IN|CN)\d{5,})\b", text, re.IGNORECASE)
    if m:
        agr, inv = m.group(1).upper(), m.group(2).upper()
        return inv, agr

    # 1) Vendor-specific (Corona) fallback for invoice refs
    inv = None
    if re.search(r"\bcorona\s+energy\b", text, re.IGNORECASE):
        for pat in [r"\bCN\d+\b", r"\bIN\d+\b", r"Invoice Number\s+(IV\d+|CN\d+)"]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                inv = (m.group(1) if m.groups() else m.group(0)).upper()
                break

    # 2) Generic invoice ref fallbacks
    if not inv:
        for pat in [
            r"\b(?:IV|IN|CN)\d{5,}\b",
            r"\b(?:Invoice|Credit\s*Note)\s*(?:Number|No\.?|#)\s*:\s*((?:IV|IN|CN)\d{3,})",
            r"\b(?:Invoice|Credit\s*Note)\s*(?:Number|No\.?|#)\s*([A-Z0-9\-]{5,})",
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                inv = (m.group(1) if m.groups() else m.group(0))
                inv = re.sub(r"\s*[-–]\s*", "-", inv).upper()
                break

    # 3) AGR detection (SSE etc.)
    agr = None
    for pat in [
        r"\bAGR\d{4,}\b",
        r"Site\s*reference\s*ID\s*(AGR\d{4,})",
        r"\bSite\s*ID\s*(AGR\d{4,})",
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            agr = (m.group(1) if m.groups() else m.group(0)).upper()
            break

    return inv, agr

def extract_refs(data: bytes) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    Returns (invoice_ref, agr_ref, supplier_hint, error_message)
    """
    try:
        with pdfplumber.open(BytesIO(data)) as pdf:
            texts = []
            for page in pdf.pages:
                t = page.extract_text() or ""
                if t:
                    texts.append(t)
            text = _normalise_text("\n".join(texts))
            if not text:
                return None, None, None, "No extractable text (scanned image PDF?)"

            supplier = _detect_supplier(text)
            inv, agr = extract_ids_from_text(text)
            return (inv.upper() if inv else None,
                    agr.upper() if agr else None,
                    supplier,
                    None)
    except Exception as e:
        return None, None, None, f"Read error: {e}"

# -------------------------------
# Renaming / zipping
# -------------------------------

def ensure_unique(name: str, existing: set) -> str:
    base, ext = os.path.splitext(name)
    candidate = name
    i = 1
    while candidate.lower() in existing:
        candidate = f"{base}_{i}{ext}"
        i += 1
    existing.add(candidate.lower())
    return candidate

def rename_and_zip_files(uploaded_files, prefix: str = "") -> Tuple[BytesIO, list]:
    """
    Returns (zip_bytes, results_list)
    results_list: dicts with original_name, agr, invoice, supplier, output_name, note
    """
    buf = BytesIO()
    results = []
    seen = set()

    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for f in uploaded_files:
            f.seek(0)
            data = f.read()

            inv, agr, supplier, err = extract_refs(data)
            note = err or ""

            if agr and inv:
                out_base = f"{prefix}{agr}-{inv}"
            elif inv:
                out_base = f"{prefix}{inv}"  # fallback if AGR missing
                if not note:
                    note = "AGR not found"
            else:
                # keep a hint of original name to help users
                orig_stem = os.path.splitext(f.name)[0]
                out_base = f"{prefix}unreadable_{_safe_filename(orig_stem)}"
                if not note:
                    note = "Invoice ref not found"

            out_name = ensure_unique(_safe_filename(out_base) + ".pdf", seen)
            z.writestr(out_name, data)

            results.append({
                "original_name": f.name,
                "agr": agr or "",
                "invoice": inv or "",
                "supplier": supplier or "",
                "output_name": out_name,
                "note": note,
            })

    buf.seek(0)
    return buf, results

# -------------------------------
# Streamlit UI
# -------------------------------

st.set_page_config(page_title="PDF Invoice Renamer", layout="centered")
st.title("PDF Invoice Renamer")
st.write("Upload one or more invoice PDFs and download them renamed. "
         "Preferred format: AGR-INV (e.g. AGR0769915-IV03223288). If one is missing, we fall back gracefully.")

with st.expander("Options", expanded=False):
    prefix = st.text_input("Optional filename prefix (e.g. account/site code):", value="")
    show_log = st.checkbox("Show extraction log table", value=True)

# Session-state counter for clearing uploader
if "uploader_index" not in st.session_state:
    st.session_state.uploader_index = 0

def clear_uploads():
    st.session_state.uploader_index += 1

st.button("🗑 Clear Uploaded Files", on_click=clear_uploads)

uploader_key = f"uploader_{st.session_state.uploader_index}"
uploaded_files = st.file_uploader(
    "Upload PDF(s)",
    type="pdf",
    accept_multiple_files=True,
    key=uploader_key
)

if uploaded_files and st.button("Process and Download"):
    with st.spinner("Processing…"):
        if len(uploaded_files) == 1:
            f = uploaded_files[0]
            f.seek(0)
            data = f.read()

            inv, agr, supplier, err = extract_refs(data)
            note = err or ""
            if agr and inv:
                base = f"{prefix}{agr}-{inv}"
            elif inv:
                base = f"{prefix}{inv}"
                if not note:
                    note = "AGR not found"
            else:
                orig_stem = os.path.splitext(f.name)[0]
                base = f"{prefix}unreadable_{_safe_filename(orig_stem)}"
                if not note:
                    note = "Invoice ref not found"

            filename = _safe_filename(base) + ".pdf"

            st.success("Done!")
            if show_log:
                st.write("**Result**")
                st.table([{
                    "original_name": f.name,
                    "agr": agr or "",
                    "invoice": inv or "",
                    "supplier": supplier or "",
                    "output_name": filename,
                    "note": note
                }])

            st.download_button(
                label="⬇️ Download Renamed PDF",
                data=data,
                file_name=filename,
                mime="application/pdf"
            )
        else:
            zipf, results = rename_and_zip_files(uploaded_files, prefix=prefix)
            st.success("Done!")
            if show_log:
                st.write("**Results**")
                st.dataframe(results, use_container_width=True)

            st.download_button(
                label="⬇️ Download Renamed PDFs as ZIP",
                data=zipf,
                file_name="renamed_invoices.zip",
                mime="application/zip"
            )
