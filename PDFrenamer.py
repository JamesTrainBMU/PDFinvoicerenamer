import streamlit as st
import re
import pdfplumber
from io import BytesIO
import zipfile

def extract_invoice_number(file):
    try:
        with pdfplumber.open(file) as pdf:
            text = "\n".join(
                page.extract_text() 
                for page in pdf.pages 
                if page.extract_text()
            )
            if "Corona Energy" in text:
                cn = re.search(r"\bCN\d+\b", text)
                if cn: return cn.group(0)
                inn = re.search(r"\bIN\d+\b", text)
                if inn: return inn.group(0)
            ivcn = re.search(r"Invoice Number\s+(IV\d+|CN\d+)", text)
            if ivcn: return ivcn.group(1)
    except Exception as e:
        st.warning(f"Could not read one of the files: {e}")
    return None

def rename_and_zip_files(uploaded_files):
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for f in uploaded_files:
            ref = extract_invoice_number(f)
            f.seek(0)
            data = f.read()
            name = f"{ref}.pdf" if ref else f"unreadable_{f.name}"
            z.writestr(name, data)
    buf.seek(0)
    return buf

# — UI setup —
st.set_page_config(page_title="PDF Invoice Renamer", layout="centered")
st.title("PDF Invoice Renamer")
st.write("Upload one or more invoice PDFs and download them renamed.")

# Session-state counter
if "uploader_index" not in st.session_state:
    st.session_state.uploader_index = 0

# Clear callback
def clear_uploads():
    st.session_state.uploader_index += 1

# 1️⃣ Clear button comes first, so it updates index before uploader runs
st.button("🗑 Clear Uploaded Files", on_click=clear_uploads)

# 2️⃣ Now build the uploader with the (possibly updated) key
uploader_key = f"uploader_{st.session_state.uploader_index}"
uploaded_files = st.file_uploader(
    "Upload PDF(s)",
    type="pdf",
    accept_multiple_files=True,
    key=uploader_key
)

# 3️⃣ Process button
if uploaded_files and st.button("Process and Download"):
    with st.spinner("Processing…"):
        if len(uploaded_files) == 1:
            f = uploaded_files[0]
            ref = extract_invoice_number(f)
            f.seek(0)
            data = f.read()
            filename = f"{ref or 'unreadable_' + f.name}.pdf"
            st.success("Done!")
            st.download_button(
                label="Download Renamed PDF",
                data=data,
                file_name=filename,
                mime="application/pdf"
            )
        else:
            zipf = rename_and_zip_files(uploaded_files)
            st.success("Done!")
            st.download_button(
                label="Download Renamed PDFs as ZIP",
                data=zipf,
                file_name="renamed_invoices.zip",
                mime="application/zip"
            )



