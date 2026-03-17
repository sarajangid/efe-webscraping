import os
import re
import requests
import shutil


def get_access_token(TENANT_ID, CLIENT_ID, CLIENT_SECRET):

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


def download_documents(BASE_DOWNLOAD_DIR, BASE_DOMAIN, grant_name, documents):

    folder = os.path.join(BASE_DOWNLOAD_DIR, safe_name(grant_name))
    os.makedirs(folder, exist_ok=True)

    for url in documents:

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


def upload_to_onedrive(USER_ID, TOKEN, local_path, remote_path):

    url = f"https://graph.microsoft.com/v1.0/users/{USER_ID}/drive/root:/{remote_path}:/content"

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

def run_storage_pipeline(
    rows,
    BASE_DOWNLOAD_DIR,
    BASE_DOMAIN,
    EXCEL_FILE,
    ONEDRIVE_FOLDER,
    TENANT_ID,
    CLIENT_ID,
    CLIENT_SECRET,
    USER_ID
):

    # 1. download documents
    for row in rows:
        download_documents(
            BASE_DOWNLOAD_DIR,
            BASE_DOMAIN,
            row["Grant Name"],
            row["Documents"]
        )

    # 2. zip documents
    zip_file = "Grants_docs.zip"
    shutil.make_archive("Grants_docs", "zip", BASE_DOWNLOAD_DIR)

    # 3. get token
    TOKEN = get_access_token(TENANT_ID, CLIENT_ID, CLIENT_SECRET)

    # 4. upload excel
    upload_to_onedrive(
        USER_ID,
        TOKEN,
        EXCEL_FILE,
        f"{ONEDRIVE_FOLDER}/Grants.xlsx"
    )

    # 5. upload zip
    upload_to_onedrive(
        USER_ID,
        TOKEN,
        zip_file,
        f"{ONEDRIVE_FOLDER}/Grants_docs.zip"
    )