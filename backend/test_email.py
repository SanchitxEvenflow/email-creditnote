import os, json
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
TOKEN_FILE = 'token.json'
CREDS_FILE = 'credentials.json'
TEST_GRN = 'G2776'

creds = None
if os.path.exists(TOKEN_FILE):
    creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

if not creds or not creds.valid:
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        flow = InstalledAppFlow.from_client_secrets_file(CREDS_FILE, SCOPES)
        creds = flow.run_local_server(port=0)
    with open(TOKEN_FILE, 'w') as f:
        f.write(creds.to_json())

service = build('gmail', 'v1', credentials=creds)

# Search for email with GRN in subject
results = service.users().messages().list(userId='me', q=f'subject:{TEST_GRN} has:attachment').execute()
messages = results.get('messages', [])
print(f'Found {len(messages)} email(s) for {TEST_GRN}')

if messages:
    msg = service.users().messages().get(userId='me', id=messages[0]['id'], format='full').execute()
    headers = {h['name']: h['value'] for h in msg['payload']['headers']}
    print('From:', headers.get('From'))
    print('Subject:', headers.get('Subject'))

    # List attachments
    parts = msg['payload'].get('parts', [])
    for part in parts:
        if part.get('filename') and part.get('body', {}).get('attachmentId'):
            print(f'Attachment: {part["filename"]} (id: {part["body"]["attachmentId"][:20]}...)')
