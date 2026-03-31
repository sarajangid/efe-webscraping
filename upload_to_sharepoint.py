import os
import re
import requests
import shutil
from dotenv import load_dotenv
#from PIL import Image
from io import BytesIO
import fitz  # PyMuPDF

load_dotenv()

TENANT_ID = os.environ["TENANT_ID"]
CLIENT_ID = os.environ["CLIENT_ID"]
CLIENT_SECRET = os.environ["CLIENT_SECRET"]
SITE_ID = os.environ["SITE_ID"]
EXCEL_FILE = os.environ["EXCEL_FILE"]
ONEDRIVE_FOLDER = os.environ["ONEDRIVE_FOLDER"]

def get_access_token():

    url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"

    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials"
    }

    response = requests.post(url, data=data)

    data = response.json()

    if "access_token" not in data:
        raise Exception(f"Token error: {data}")

    return data["access_token"]


def safe_name(name):
    clean = re.sub(r'[<>:"/\\|?*]', "", name)
    return clean[:120]


'''def download_documents_helper(BASE_DOWNLOAD_DIR, BASE_DOMAIN, grant_name, documents):

    for url in documents:

        folder = os.path.join(BASE_DOWNLOAD_DIR, safe_name(grant_name))
        os.makedirs(folder, exist_ok=True)

        if not url.startswith("http"):
            url = BASE_DOMAIN + url

        filename = url.split("/")[-1]
        filepath = os.path.join(folder, filename)

        if os.path.exists(filepath):
            continue

        try:
            r = requests.get(url, stream=True)

            with open(filepath, "wb") as f:
                for chunk in r.iter_content(8192):
                    f.write(chunk)

            print("Downloaded:", filename)

        except Exception as e:
            print("Download error:", e)'''

def download_documents_helper(BASE_DOWNLOAD_DIR, BASE_DOMAIN, grant_name, documents):

    for url in documents:

        folder = os.path.join(BASE_DOWNLOAD_DIR, safe_name(grant_name))
        os.makedirs(folder, exist_ok=True)

        if not url.startswith("http"):
            url = BASE_DOMAIN + url

        original_filename = url.split("/")[-1]
        stem = os.path.splitext(original_filename)[0]
        pdf_filename = stem + ".pdf"
        filepath = os.path.join(folder, pdf_filename)

        if os.path.exists(filepath):
            continue

        try:
            r = requests.get(url, stream=True)
            r.raise_for_status()

            content_type = r.headers.get("Content-Type", "")
            raw = r.content

            # Already a PDF
            if "pdf" in content_type or original_filename.lower().endswith(".pdf"):
                with open(filepath, "wb") as f:
                    f.write(raw)

            # Image → PDF
            elif "image" in content_type or original_filename.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff")):
                #img = Image.open(BytesIO(raw)).convert("RGB")
                #img.save(filepath, "PDF")
                img_doc = fitz.open(stream=raw, filetype="image")
                pdf_bytes = img_doc.convert_to_pdf()
                img_doc.close()
                with open(filepath, "wb") as f:
                    f.write(pdf_bytes)

            # HTML / text → PDF via PyMuPDF
            elif "html" in content_type or original_filename.lower().endswith((".html", ".htm")):
                doc = fitz.open()
                page = doc.new_page()
                page.insert_text((72, 72), raw.decode("utf-8", errors="replace"), fontsize=10)
                doc.save(filepath)
                doc.close()

            # Word documents → PDF via LibreOffice (if available)
            elif original_filename.lower().endswith((".doc", ".docx")):
                tmp_path = os.path.join(folder, original_filename)
                with open(tmp_path, "wb") as f:
                    f.write(raw)
                os.system(f'libreoffice --headless --convert-to pdf "{tmp_path}" --outdir "{folder}"')
                if os.path.exists(filepath):
                    os.remove(tmp_path)

            # Fallback: wrap raw bytes in a PDF as plain text
            else:
                doc = fitz.open()
                page = doc.new_page()
                try:
                    text = raw.decode("utf-8", errors="replace")
                except Exception:
                    text = f"[Binary content from: {url}]"
                page.insert_text((72, 72), text, fontsize=10)
                doc.save(filepath)
                doc.close()

            print("Downloaded as PDF:", pdf_filename)

        except Exception as e:
            print("Download error:", e)


def upload_to_onedrive(TOKEN, local_path, remote_path):

    url = f"https://graph.microsoft.com/v1.0/sites/{SITE_ID}/drive/root:/{remote_path}:/content"

    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/octet-stream"
    }

    with open(local_path, "rb") as f:
        r = requests.put(url, headers=headers, data=f)

        if r.status_code not in [200, 201]:
            print("Upload failed:", r.text)
        else:
            print("Uploaded:", remote_path)

    print("Uploaded:", remote_path)

def download_documents(
    rows,
    BASE_DOWNLOAD_DIR,
    BASE_DOMAIN,
    grant_name_col,
    docs_arr_col
):

    # 1. download documents
    for row in rows:
        download_documents_helper(
            BASE_DOWNLOAD_DIR,
            BASE_DOMAIN,
            row[grant_name_col],
            row[docs_arr_col]
        )




def process_uploads():

    DIR = os.environ["BASE_DOWNLOAD_DIR"]

    # 2. zip documents
    shutil.make_archive("Grants_docs", "zip", DIR)

    # 3. get token
    TOKEN = get_access_token()

    # 4. upload excel
    upload_to_onedrive(
        TOKEN,
        EXCEL_FILE,
        f"{ONEDRIVE_FOLDER}/Grants.xlsx",
    )

    # 5. upload zip
    upload_to_onedrive(
        TOKEN,
        "Grants_docs.zip",
        f"{ONEDRIVE_FOLDER}/Grants_docs.zip",
    )