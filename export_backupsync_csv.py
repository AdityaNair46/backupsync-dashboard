"""
export_backupsync_csv.py
────────────────────────
Reads the RevolutionBackupsync Google Sheet, exports all historical
backup sync data to backupsync_historic.csv, then pushes it to GitHub
so the dashboard at https://AdityaNair46.github.io/backupsync-dashboard
auto-updates.

Usage:
  python export_backupsync_csv.py

First-time setup:
  Set your GitHub token in one of two ways:
    1. Environment variable (recommended):
         Windows: setx GITHUB_TOKEN "your_token_here"
         then restart VS Code
    2. Paste it directly into GITHUB_TOKEN below (less secure)

Dependencies:
  pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client requests
"""

import os
import csv
import base64
import json
from datetime import datetime

import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# ── Config ────────────────────────────────────────────────────────────────────

SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']

SPREADSHEET_ID      = '1ClAOFd9Q1OEFLL8EZtPvv-1P5wGVMxM7greEpXkip74'
SHEET_NAME          = 'RevolutionBackupsync'
LOCATIONS_START_ROW = 2

OUTPUT_CSV = 'backupsync_historic.csv'

# GitHub settings
GITHUB_USERNAME = 'AdityaNair46'
GITHUB_REPO     = 'backupsync-dashboard'
GITHUB_BRANCH   = 'main'
GITHUB_CSV_PATH = 'backupsync_historic.csv'   # path inside the repo

# Put your token here OR set env var GITHUB_TOKEN (recommended)
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', 'PASTE_YOUR_TOKEN_HERE')

# ── Auth ──────────────────────────────────────────────────────────────────────

def get_sheets_service():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as f:
            f.write(creds.to_json())
    return build('sheets', 'v4', credentials=creds)

# ── Sheet helpers ─────────────────────────────────────────────────────────────

def get_sheet_id(service):
    meta = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    for sheet in meta['sheets']:
        if sheet['properties']['title'] == SHEET_NAME:
            return sheet['properties']['sheetId']
    available = [s['properties']['title'] for s in meta['sheets']]
    raise ValueError(f"Tab '{SHEET_NAME}' not found. Available: {available}")

def read_all_grid_data(service, sheet_id):
    result = service.spreadsheets().get(
        spreadsheetId=SPREADSHEET_ID,
        includeGridData=True,
        ranges=[]
    ).execute()
    for sheet in result['sheets']:
        if sheet['properties']['sheetId'] == sheet_id:
            grid     = sheet.get('data', [{}])[0]
            rows_raw = grid.get('rowData', [])
            rows = []
            for row in rows_raw:
                cells    = row.get('values', [])
                row_vals = []
                for c in cells:
                    ev = c.get('effectiveValue', {})
                    if 'boolValue' in ev:
                        row_vals.append('TRUE' if ev['boolValue'] else 'FALSE')
                    else:
                        row_vals.append(
                            c.get('formattedValue') or
                            ev.get('stringValue', '') or ''
                        )
                rows.append(row_vals)
            return rows
    return []

def pad_row(row, length):
    return row + [''] * max(0, length - len(row))

# ── Export to CSV ─────────────────────────────────────────────────────────────

def export_to_csv(service):
    sheet_id = get_sheet_id(service)
    print(f"📖 Reading sheet '{SHEET_NAME}'…")
    rows = read_all_grid_data(service, sheet_id)

    if not rows:
        print("⚠️  Sheet appears empty — nothing to export.")
        return False

    header_row = rows[0] if rows else []
    date_cols  = []
    for col_idx, cell in enumerate(header_row):
        if col_idx == 0:
            continue
        val = cell.strip()
        if val:
            date_cols.append((col_idx, val))

    if not date_cols:
        print("⚠️  No date columns found in row 1.")
        return False

    print(f"📅 Found {len(date_cols)} date column(s): "
          f"{date_cols[0][1]} → {date_cols[-1][1]}")

    location_rows = []
    for r_idx in range(LOCATIONS_START_ROW - 1, len(rows)):
        row      = pad_row(rows[r_idx], max(c for c, _ in date_cols) + 1)
        loc_name = row[0].strip()
        if loc_name:
            location_rows.append((loc_name, row))

    print(f"📍 Found {len(location_rows)} location row(s)")

    records = []
    for loc_name, row in location_rows:
        for col_idx, date_str in date_cols:
            cell_val  = row[col_idx].strip().upper() if col_idx < len(row) else ''
            completed = cell_val in ('TRUE', '1', 'YES')
            records.append({
                'date':      date_str,
                'location':  loc_name,
                'completed': 'TRUE' if completed else 'FALSE',
            })

    def sort_key(r):
        try:
            return (datetime.strptime(r['date'], '%Y-%m-%d'), r['location'])
        except ValueError:
            return (datetime.min, r['location'])

    records.sort(key=sort_key)

    with open(OUTPUT_CSV, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['date', 'location', 'completed'])
        writer.writeheader()
        writer.writerows(records)

    total     = len(records)
    completed = sum(1 for r in records if r['completed'] == 'TRUE')
    dates     = sorted({r['date'] for r in records})

    print(f"\n{'=' * 55}")
    print(f"✅ CSV saved → {OUTPUT_CSV}")
    print(f"{'=' * 55}")
    print(f"  Total records : {total:,}")
    if total:
        print(f"  Completed     : {completed:,}  ({100 * completed / total:.1f}%)")
    print(f"  Incomplete    : {total - completed:,}")
    if dates:
        print(f"  Date range    : {dates[0]} → {dates[-1]}")
    return True

# ── GitHub push ───────────────────────────────────────────────────────────────

def push_csv_to_github():
    if GITHUB_TOKEN == 'PASTE_YOUR_TOKEN_HERE':
        print("\n⚠️  GitHub token not set — skipping push.")
        print("   Set env var GITHUB_TOKEN or paste token into the script.")
        return

    print(f"\n📤 Pushing CSV to GitHub ({GITHUB_USERNAME}/{GITHUB_REPO})…")

    with open(OUTPUT_CSV, 'rb') as f:
        content_b64 = base64.b64encode(f.read()).decode('utf-8')

    api_url = (f"https://api.github.com/repos/{GITHUB_USERNAME}/"
               f"{GITHUB_REPO}/contents/{GITHUB_CSV_PATH}")
    headers = {
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept':        'application/vnd.github.v3+json',
    }

    # Check if file already exists (need its SHA to update)
    existing = requests.get(api_url, headers=headers)
    sha = existing.json().get('sha') if existing.status_code == 200 else None

    now_str = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
    payload = {
        'message': f'Auto-update backup sync data — {now_str}',
        'content': content_b64,
        'branch':  GITHUB_BRANCH,
    }
    if sha:
        payload['sha'] = sha   # required for updates

    response = requests.put(api_url, headers=headers, data=json.dumps(payload))

    if response.status_code in (200, 201):
        action = 'Updated' if sha else 'Created'
        print(f"  ✅ {action} — dashboard will refresh in ~60 seconds")
        print(f"  🌐 https://{GITHUB_USERNAME}.github.io/{GITHUB_REPO}/")
    else:
        print(f"  🛑 GitHub push failed: {response.status_code}")
        print(f"     {response.json().get('message', response.text)}")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    try:
        service = get_sheets_service()
        success = export_to_csv(service)
        if success:
            push_csv_to_github()
    except Exception as e:
        print(f"🛑 Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()
