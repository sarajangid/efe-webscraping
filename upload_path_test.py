import requests
from upload_to_sharepoint import get_access_token, _sharepoint_env

def test_upload_path():
    cfg = _sharepoint_env()
    TOKEN = get_access_token()
    site_id = cfg["SITE_ID"]
    drive_id = cfg["DRIVE_ID"]
    folder = cfg["ONEDRIVE_FOLDER"]

    # 1. List all drives so you can confirm DRIVE_ID matches "Programs"
    print("\n=== DRIVES ===")
    r = requests.get(
        f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives",
        headers={"Authorization": f"Bearer {TOKEN}"}
    )
    for d in r.json().get("value", []):
        marker = " ✅ (this is your DRIVE_ID)" if d["id"] == drive_id else ""
        print(f"  {d['name']} → {d['id']}{marker}")

    # 2. Upload a small test file
    test_filename = "_test_upload.txt"
    remote_path = f"{folder}/{test_filename}"
    upload_url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives/{drive_id}/root:/{remote_path}:/content"

    print(f"\n=== UPLOADING to: {remote_path} ===")
    r = requests.put(
        upload_url,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "text/plain"},
        data=b"hello from test upload"
    )
    print(f"  Status: {r.status_code}")
    if r.status_code in [200, 201]:
        info = r.json()
        print(f"  File name : {info.get('name')}")
        print(f"  Web URL   : {info.get('webUrl')}")  # <-- click this link to see exactly where it landed
    else:
        print(f"  Error: {r.text}")

    # 3. Try to download it back
    print(f"\n=== DOWNLOADING back: {remote_path} ===")
    r = requests.get(
        f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives/{drive_id}/root:/{remote_path}:/content",
        headers={"Authorization": f"Bearer {TOKEN}"},
        allow_redirects=True
    )
    print(f"  Status: {r.status_code}")
    if r.status_code == 200:
        print(f"  Content: {r.content}")
        print("\n✅ Upload and download both worked — path is correct")
    else:
        print(f"\n❌ Download failed: {r.text}")

if __name__ == "__main__":
    test_upload_path()