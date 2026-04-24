import os
import re
import requests
import shutil
from dotenv import load_dotenv
#from PIL import Image
from io import BytesIO
import fitz  # PyMuPDF

load_dotenv()

_SHAREPOINT_ENV_KEYS = (
    "TENANT_ID",
    "CLIENT_ID",
    "CLIENT_SECRET",
    "SITE_ID",
    "EXCEL_FILE",
    "ONEDRIVE_FOLDER",
    "DRIVE_ID"
)


def _sharepoint_env():
    missing = [k for k in _SHAREPOINT_ENV_KEYS if not os.getenv(k)]
    if missing:
        raise RuntimeError(
            "SharePoint upload needs these variables (set in the environment or a .env file): "
            + ", ".join(missing)
        )
    return {k: os.environ[k] for k in _SHAREPOINT_ENV_KEYS}

def get_access_token():
    cfg = _sharepoint_env()
    url = f"https://login.microsoftonline.com/{cfg['TENANT_ID']}/oauth2/v2.0/token"

    data = {
        "client_id": cfg["CLIENT_ID"],
        "client_secret": cfg["CLIENT_SECRET"],
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


def download_from_onedrive(TOKEN, remote_path, local_path):
    """Download a file from SharePoint/OneDrive to a local path.

    Returns True if the file was downloaded, False if it doesn't exist yet
    (e.g. first-ever run), and raises on any other error.
    """
    cfg = _sharepoint_env()
    url = f"https://graph.microsoft.com/v1.0/sites/{cfg['SITE_ID']}/drives/{cfg['DRIVE_ID']}/root:/{remote_path}:/content"

    headers = {"Authorization": f"Bearer {TOKEN}"}
    r = requests.get(url, headers=headers, allow_redirects=True)

    if r.status_code == 404:
        print(f"No existing file at {remote_path} — will create on first upload.")
        return False

    if r.status_code not in [200, 302]:
        raise RuntimeError(f"Download failed ({r.status_code}): {r.text}")

    os.makedirs(os.path.dirname(os.path.abspath(local_path)), exist_ok=True)
    with open(local_path, "wb") as f:
        f.write(r.content)
    print(f"Downloaded {remote_path} → {local_path}")
    return True


def upload_to_onedrive(TOKEN, local_path, remote_path):
    cfg = _sharepoint_env()
    url = f"https://graph.microsoft.com/v1.0/sites/{cfg['SITE_ID']}/drives/{cfg['DRIVE_ID']}/root:/{remote_path}:/content"

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




def download_excel():
    """Download the existing Grants.xlsx from SharePoint to the local EXCEL_FILE path.

    Call this before running scrapers so they can dedup against existing data.
    Does nothing (and doesn't raise) if the file doesn't exist on SharePoint yet.
    """
    cfg = _sharepoint_env()
    TOKEN = get_access_token()
    return download_from_onedrive(
        TOKEN,
        f"{cfg['ONEDRIVE_FOLDER']}/Grants.xlsx",
        cfg["EXCEL_FILE"],
    )


def download_docs():
    """Download Grants_docs.zip from SharePoint and unzip it to BASE_DOWNLOAD_DIR.

    Call this before running scrapers so previously downloaded PDFs are restored
    and download_documents_helper skips files that already exist.
    Does nothing (and doesn't raise) if the zip doesn't exist on SharePoint yet.
    """
    cfg = _sharepoint_env()
    dir_key = "BASE_DOWNLOAD_DIR"
    if not os.getenv(dir_key):
        raise RuntimeError(
            f"{dir_key} must be set (environment or .env) for doc downloads."
        )
    DIR = os.environ[dir_key]
    TOKEN = get_access_token()
    downloaded = download_from_onedrive(
        TOKEN,
        f"{cfg['ONEDRIVE_FOLDER']}/Grants_docs.zip",
        "Grants_docs.zip",
    )
    if downloaded:
        os.makedirs(DIR, exist_ok=True)
        shutil.unpack_archive("Grants_docs.zip", DIR)
        print(f"Unzipped docs to {DIR}")
    return downloaded


def process_uploads():
    cfg = _sharepoint_env()
    dir_key = "BASE_DOWNLOAD_DIR"
    if not os.getenv(dir_key):
        raise RuntimeError(
            f"{dir_key} must be set (environment or .env) for zipping uploads."
        )
    DIR = os.environ[dir_key]

    # 2. zip documents
    shutil.make_archive("Grants_docs", "zip", DIR)

    # 3. get token
    TOKEN = get_access_token()

    # 4. upload excel
    upload_to_onedrive(
        TOKEN,
        cfg["EXCEL_FILE"],
        f"{cfg['ONEDRIVE_FOLDER']}/Grants.xlsx",
    )

    # 5. upload zip
    upload_to_onedrive(
        TOKEN,
        "Grants_docs.zip",
        f"{cfg['ONEDRIVE_FOLDER']}/Grants_docs.zip",
    )
