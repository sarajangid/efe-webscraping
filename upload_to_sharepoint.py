import os
import re
import requests
import shutil
from dotenv import load_dotenv

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


def download_documents_helper(BASE_DOWNLOAD_DIR, BASE_DOMAIN, grant_name, documents):

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
            print("Download error:", e)


def upload_to_onedrive(SITE_ID, TOKEN, local_path, remote_path):

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
        f"{ONEDRIVE_FOLDER}/Grants.xlsx"
    )

    # 5. upload zip
    upload_to_onedrive(
        TOKEN,
        "Grants_docs.zip",
        f"{ONEDRIVE_FOLDER}/Grants_docs.zip"
    )