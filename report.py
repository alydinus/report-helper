import csv
import io
import os
import sys
import time

from google import genai
from google.genai import errors as genai_errors
from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
RETRYABLE_CODES = {429, 500, 502, 503, 504}


def env(name: str, default: str | None = None, *, required: bool = False) -> str:
    val = os.environ.get(name, default)
    if required and not val:
        raise RuntimeError(f"{name} is not set")
    return val or ""


SPREADSHEET_ID = env("SPREADSHEET_ID", required=True)
SHEET_NAME = env("SHEET_NAME")
SERVICE_ACCOUNT_FILE = env("SERVICE_ACCOUNT_FILE", "service-account.json")
PROMPT_FILE = env("PROMPT_FILE", "prompt.txt")
EXPECTED_COLUMNS = int(env("EXPECTED_COLUMNS", "0") or 0)
START_COLUMN = env("START_COLUMN", "A")

GEMINI_API_KEY = env("GEMINI_API_KEY", required=True)
GEMINI_MODELS = [
    m.strip()
    for m in env(
        "GEMINI_MODELS",
        "gemini-2.5-flash,gemini-2.5-flash-lite,gemini-2.0-flash",
    ).split(",")
    if m.strip()
]
GEMINI_MAX_RETRIES = int(env("GEMINI_MAX_RETRIES", "3"))


def column_letter(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def load_prompt(path: str, **vars: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        tmpl = f.read()
    for k, v in vars.items():
        tmpl = tmpl.replace("{{" + k + "}}", v)
    return tmpl


def format_with_gemini(prompt: str) -> list[str]:
    client = genai.Client(api_key=GEMINI_API_KEY)

    last_err: Exception | None = None
    text = ""
    for model in GEMINI_MODELS:
        for attempt in range(1, GEMINI_MAX_RETRIES + 1):
            try:
                resp = client.models.generate_content(model=model, contents=prompt)
                text = (resp.text or "").strip()
                print(f"gemini ok model={model} attempt={attempt}", file=sys.stderr)
                break
            except genai_errors.APIError as e:
                code = getattr(e, "code", None)
                last_err = e
                if code in RETRYABLE_CODES and attempt < GEMINI_MAX_RETRIES:
                    delay = 2 ** (attempt - 1)
                    print(
                        f"gemini retryable error model={model} attempt={attempt} code={code}; sleeping {delay}s",
                        file=sys.stderr,
                    )
                    time.sleep(delay)
                    continue
                print(
                    f"gemini failed model={model} attempt={attempt} code={code}: {e}",
                    file=sys.stderr,
                )
                break
        if text:
            break
    if not text:
        raise last_err if last_err else RuntimeError("gemini: no models returned text")

    print(f"gemini raw response: {text!r}", file=sys.stderr)

    if text.startswith("```"):
        text = text.strip("`")
        if "\n" in text:
            text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0].strip()

    line = next((ln for ln in text.splitlines() if ln.strip()), "")
    if not line:
        raise ValueError("Gemini returned empty response")
    row = next(csv.reader(io.StringIO(line)))
    if EXPECTED_COLUMNS and len(row) != EXPECTED_COLUMNS:
        raise ValueError(
            f"Gemini returned {len(row)} columns, expected {EXPECTED_COLUMNS}: {row!r}"
        )
    return [c.strip() for c in row]


def pad_or_trim(values: list[str], size: int) -> list[str]:
    if len(values) >= size:
        return values[:size]
    return values + [""] * (size - len(values))


date = sys.argv[1]
commit_hash = sys.argv[2]
message = sys.argv[3]

prompt = load_prompt(PROMPT_FILE, date=date, commit_hash=commit_hash, message=message)

try:
    row = format_with_gemini(prompt)
except Exception as e:
    print(f"gemini formatting failed, falling back to raw values: {e}", file=sys.stderr)
    row = [date, commit_hash, message]
    if EXPECTED_COLUMNS:
        row = pad_or_trim(row, EXPECTED_COLUMNS)

print(f"row to append: {row!r}", file=sys.stderr)

creds = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE,
    scopes=SCOPES,
)
service = build("sheets", "v4", credentials=creds)

sheet_name = SHEET_NAME
if not sheet_name:
    meta = service.spreadsheets().get(
        spreadsheetId=SPREADSHEET_ID,
        fields="sheets.properties.title",
    ).execute()
    sheet_name = meta["sheets"][0]["properties"]["title"]

end_column = column_letter(EXPECTED_COLUMNS or len(row))
sheet_range = f"{sheet_name}!{START_COLUMN}:{end_column}"

service.spreadsheets().values().append(
    spreadsheetId=SPREADSHEET_ID,
    range=sheet_range,
    valueInputOption="USER_ENTERED",
    insertDataOption="INSERT_ROWS",
    body={"values": [row]},
).execute()
