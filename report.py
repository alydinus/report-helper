import csv
import io
import os
import sys
import time

from google import genai
from google.genai import errors as genai_errors
from google.oauth2 import service_account
from googleapiclient.discovery import build

SPREADSHEET_ID = "1e9PTXF1ph3oupVzE9NqGey-qxUzM72fnZe2Vi2J4GmQ"
SERVICE_ACCOUNT_FILE = "service-account.json"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

GEMINI_MODELS = [
    m.strip()
    for m in os.environ.get(
        "GEMINI_MODELS",
        "gemini-2.5-flash,gemini-2.5-flash-lite,gemini-2.0-flash",
    ).split(",")
    if m.strip()
]
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MAX_RETRIES = int(os.environ.get("GEMINI_MAX_RETRIES", "3"))
RETRYABLE_CODES = {429, 500, 502, 503, 504}

date = sys.argv[1]
commit_hash = sys.argv[2]
message = sys.argv[3]


def format_with_gemini(date: str, commit_hash: str, message: str) -> list[str]:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set")

    prompt = (
        "Ты помощник по учёту рабочего времени. На вход даётся git-коммит. "
        "Сформируй ОДНУ строку CSV (разделитель — запятая, поля с запятыми/переводами строк бери в двойные кавычки) "
        "ровно с пятью колонками в таком порядке: Дата,Задача,Описание,Сложность,Часы.\n"
        "Правила:\n"
        "- Дата: используй переданное значение как есть.\n"
        "- Задача: короткий заголовок (тип + область), 3–6 слов, по сути коммита.\n"
        "- Описание: 1–2 предложения по-русски, что именно сделано.\n"
        "- Сложность: одно из Низкая/Средняя/Высокая.\n"
        "- Часы: целое число от 1 до 8, реалистичная оценка.\n"
        "Не добавляй заголовок, не добавляй markdown, не оборачивай в ```. Верни ровно одну строку CSV.\n\n"
        f"Дата: {date}\n"
        f"Хеш: {commit_hash}\n"
        f"Сообщение коммита:\n{message}\n"
    )

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
    if len(row) != 5:
        raise ValueError(f"Gemini returned {len(row)} columns, expected 5: {row!r}")
    return [c.strip() for c in row]


try:
    row = format_with_gemini(date, commit_hash, message)
except Exception as e:
    print(f"gemini formatting failed, falling back to raw values: {e}", file=sys.stderr)
    row = [date, commit_hash, message, "", ""]

print(f"row to append: {row!r}", file=sys.stderr)

creds = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE,
    scopes=SCOPES,
)
service = build("sheets", "v4", credentials=creds)

meta = service.spreadsheets().get(
    spreadsheetId=SPREADSHEET_ID,
    fields="sheets.properties.title",
).execute()
sheet_name = meta["sheets"][0]["properties"]["title"]

service.spreadsheets().values().append(
    spreadsheetId=SPREADSHEET_ID,
    range=f"{sheet_name}!A:E",
    valueInputOption="USER_ENTERED",
    insertDataOption="INSERT_ROWS",
    body={"values": [row]},
).execute()
