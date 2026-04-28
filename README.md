# report-helper

Утилита, которая после каждого `git commit` отправляет данные коммита в Gemini, получает структурированную CSV-строку и дописывает её в Google Sheets. Полезно для автоматического учёта рабочего времени или changelog'а.

## Содержание

- [Как это работает](#как-это-работает)
- [Требования](#требования)
- [Получение API-ключей](#получение-api-ключей)
  - [1. Gemini API key](#1-gemini-api-key)
  - [2. Service Account для Google Sheets](#2-service-account-для-google-sheets)
  - [3. Подготовка Google Sheet](#3-подготовка-google-sheet)
- [Установка](#установка)
- [Использование](#использование)
- [Per-repo переопределения](#per-repo-переопределения)
- [Кастомизация промпта](#кастомизация-промпта)
- [Диагностика](#диагностика)
- [Удаление](#удаление)

## Как это работает

```
git commit ──► .git/hooks/post-commit ──► report-helper run
                                              │
                                              ▼
                                     docker run (image: report)
                                              │
                                              ├─► Gemini API   (форматирует CSV-строку)
                                              └─► Sheets API   (append в указанный лист)
```

Конфигурация — каскадная:

1. `~/.config/report-helper/.env` — глобальная (одна на всю систему)
2. `<repo>/.report-helper/.env` — опциональная, для конкретного репо

## Требования

- Docker
- Bash, Git
- Каталог в `PATH`, куда положим симлинк CLI (по умолчанию `~/.local/bin`)

## Получение API-ключей

### 1. Gemini API key

1. Открой https://aistudio.google.com/app/apikey
2. Войди под Google-аккаунтом
3. Нажми **«Create API key»** → выбери проект (или создай новый)
4. Скопируй ключ — понадобится для переменной `GEMINI_API_KEY`

Бесплатный тариф позволяет ~15 RPM на `gemini-2.5-flash` — этого с запасом хватает для коммитов.

### 2. Service Account для Google Sheets

Запись в Google Sheets идёт через сервис-аккаунт (без OAuth-флоу).

1. Открой https://console.cloud.google.com/ и создай проект (или используй существующий).
2. **APIs & Services → Library** → найди **Google Sheets API** → **Enable**.
3. **IAM & Admin → Service Accounts** → **Create Service Account**:
   - Name: `report-helper` (любое)
   - Role: можно пропустить, для записи в конкретную таблицу роли проекта не нужны
4. На странице созданного сервис-аккаунта → **Keys → Add Key → Create new key → JSON** → скачай файл.
5. Сохрани его как `service-account.json`.
6. Запомни email сервис-аккаунта вида `report-helper@<project>.iam.gserviceaccount.com` — он понадобится на следующем шаге.

### 3. Подготовка Google Sheet

1. Создай (или открой существующую) таблицу — https://sheets.new
2. Скопируй её ID из URL: `https://docs.google.com/spreadsheets/d/`**`<SPREADSHEET_ID>`**`/edit`
3. Нажми **Share** в правом верхнем углу, добавь email сервис-аккаунта с ролью **Editor**.
4. (Опционально) Создай заголовки колонок в первой строке — например `Дата | Задача | Описание | Сложность | Часы` для дефолтного промпта.

## Установка

```bash
# 1. Клонируй репо в любое место
git clone <url> ~/Projects/report-helper
cd ~/Projects/report-helper

# 2. Создай глобальный конфиг и шаблоны
./bin/report-helper bootstrap

# 3. Положи скачанный JSON-ключ в глобальный конфиг
mv ~/Downloads/service-account-*.json ~/.config/report-helper/service-account.json

# 4. Заполни ~/.config/report-helper/.env
#    Минимум: SPREADSHEET_ID и GEMINI_API_KEY
${EDITOR:-nano} ~/.config/report-helper/.env

# 5. Положи CLI в PATH
./bin/report-helper link
# (если ~/.local/bin не в PATH, добавь в ~/.bashrc:
#   export PATH="$HOME/.local/bin:$PATH"
# и перезапусти оболочку)

# 6. Собери docker-образ (один раз)
report-helper build

# 7. Проверь состояние
report-helper status
```

`report-helper status` должен показать «built», все ключевые env заполнены, `GEMINI_API_KEY: <set, N chars>`.

## Использование

В каждом репо, где нужно автоматически логировать коммиты:

```bash
cd /path/to/your/project
report-helper install        # ставит .git/hooks/post-commit (асинхронный)
```

Теперь любой `git commit` в этом репо допишет строку в твою таблицу. Хук неблокирующий — `git commit` возвращается мгновенно, отчёт уходит в фоне.

Ручной прогон (например, для теста или повторной отправки):

```bash
report-helper run                # для HEAD
report-helper run abc1234        # для конкретного коммита
```

Удалить хук:

```bash
report-helper uninstall
```

## Per-repo переопределения

Если в конкретном репо нужны другие настройки (другая таблица, другой промпт, другой сервис-аккаунт):

```bash
cd /path/to/project
report-helper init           # создаёт .report-helper/.env и добавляет в .gitignore
${EDITOR:-nano} .report-helper/.env
```

В `.report-helper/.env` достаточно указать только то, что отличается от глобального конфига. Например:

```bash
SPREADSHEET_ID=другой_id_таблицы
SHEET_NAME=Project-A
EXPECTED_COLUMNS=3
```

Внутри docker-контейнера per-repo каталог монтируется в `/config-repo`, глобальный — в `/config`. Поэтому если хочешь использовать локальный сервис-аккаунт или промпт, в `.report-helper/.env` укажи:

```bash
SERVICE_ACCOUNT_FILE=/config-repo/service-account.json
PROMPT_FILE=/config-repo/prompt.txt
```

…и положи соответствующие файлы в `<repo>/.report-helper/`.

## Кастомизация промпта

Глобальный промпт — `~/.config/report-helper/prompt.txt`. По умолчанию он генерирует пять колонок (`Дата, Задача, Описание, Сложность, Часы`) на русском.

Доступные плейсхолдеры (заменяются перед отправкой в Gemini):

- `{{date}}` — дата коммита
- `{{commit_hash}}` — короткий хеш
- `{{message}}` — сообщение коммита

Если меняешь количество колонок, обнови `EXPECTED_COLUMNS` в `.env`. При `EXPECTED_COLUMNS=0` валидация выключается, и в таблицу пишется ровно столько колонок, сколько вернул Gemini.

## Диагностика

```bash
report-helper status
```

Логи последних запусков — в `<repo>/hook.log` (или там, куда указывает `REPORT_LOG_FILE`).

Часто встречающиеся проблемы:

| Симптом | Причина | Решение |
|---|---|---|
| `required env vars not set: SPREADSHEET_ID` | пустой `.env` | заполни `~/.config/report-helper/.env` |
| `docker: permission denied` | юзер не в группе docker | `sudo usermod -aG docker $USER`, перелогинься |
| `403` от Sheets API | сервис-аккаунт не добавлен в Share | поделись таблицей с email сервис-аккаунта |
| `429` от Gemini | rate limit | `GEMINI_MODELS` уже задаёт фоллбэк, или подожди |
| хук установлен, но строки не появляются | хук асинхронный, ошибка ушла в лог | смотри `<repo>/hook.log` |
| `git commit` блокируется на несколько секунд | стоит синхронный хук | `report-helper uninstall && report-helper install` (без `--sync`) |

Альтернативный режим хука для отладки (синхронный, ошибки печатаются сразу):

```bash
report-helper install --sync
```

## Удаление

```bash
# В каждом репо, где стоял хук
report-helper uninstall

# Из системы
rm ~/.local/bin/report-helper
docker image rm report
rm -rf ~/.config/report-helper
```
