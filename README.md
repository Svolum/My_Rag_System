# RAG по Obsidian заметкам с бд=pgvector и Gemini в качестве ответчика

Локальная Retrieval-Augmented Generation (RAG) система для семантического поиска и ответов на вопросы по базе заметок Obsidian. В качестве векторного хранилища используется PostgreSQL с расширением `pgvector`, за векторизацию отвечает `multilingual-e5-large`, а ответы генерируются с помощью Google Gemini API, хотя можно и без него, но так будет больно читать 100 или больше выпавших ответов т.к. нормально текст на чанки разбит не был.

---

## 🚀 Основные возможности

* **не автоматическая разметка заметок Obsidian:** Скрипт `id_genchik.py` добавляет уникальные `uuid` в YAML frontmatter(свойства) каждой заметки и ведет реестр в локальной SQLite базе.
* **Умная инкрементальная индексация:** `indexer.py` отслеживает изменения каждой заметки через MD5-хэши в `state.json`. Переиндексируются только новые или измененные файлы, а удаленные из Obsidian заметки автоматически очищаются из векторной БД (Garbage Collection).
* **CLI-чат:** Консольный интерфейс на базе библиотеки `Rich`.

---

## 🛠 Архитектура и стек

* **База данных:** PostgreSQL 16 + `pgvector` (развертывание через Docker Compose, используется контейнер тк так проще чем накручивать простую бд)
* **Модель эмбеддингов:** `intfloat/multilingual-e5-large` (`sentence-transformers`, размерность вектора — 1024, длина чанка где-то > 300 символов)
* **Сплиттер текста:** `RecursiveCharacterTextSplitter` (`langchain-text-splitters`, не знаю что это и за что отвечает)
* **LLM генерация:** Google Gemini (`google-genai` SDK)
* **Консольный интерфейс:** `rich`

---

## 📁 Структура проекта

```text
.
├── docker-compose.yml       # Конфигурация контейнера PostgreSQL + pgvector
├── .gitignore               # Исключения для Git
├── exemple.env              # Шаблон переменных окружения для Docker
└── norm_rag/
    ├── exemple.env          # Шаблон переменных окружения для Python-скриптов
    ├── id_genchik.py        # Генератор UUID для заметок Obsidian (YAML frontmatter)
    ├── indexer.py           # Чанкинг, векторизация и сохранение в БД
    └── searcher.py          # Консольный чат-бот и семантический поиск
```

---

## ⚡ Быстрый старт

### 1. Подготовка окружения

Клонируйте репозиторий, создайте виртуальное окружение и установите зависимости:

```bash
python -m venv .venv

# Активация для Windows:
.venv\Scripts\activate
# Активация для Linux / macOS:
source .venv/bin/activate

pip install psycopg2-binary sentence-transformers langchain-text-splitters google-genai rich pyyaml python-dotenv
```

### 2. Настройка переменных окружения (`.env`)

Создайте рабочие файлы `.env` из шаблонов:

1. В корне проекта (для Docker):
   ```bash
   cp exemple.env .env
   ```
2. В папке `norm_rag/` (для скриптов):
   ```bash
   cp norm_rag/exemple.env norm_rag/.env
   ```

Откройте `norm_rag/.env` и укажите ваши данные:
* `VAULT_PATH` — полный путь к вашей папке с заметками Obsidian.
* `GEMINI_API_KEY` — ваш ключ API из Google AI Studio.

### 3. Запуск и инициализация базы данных

Запустите контейнер с PostgreSQL:

```bash
docker compose up
```

Подключитесь к базе данных (по умолчанию порт `5433`, пользователь `rag_user`, пароль `rag_password`, БД `rag_db`) и выполните SQL-запрос для создания расширения и таблицы:

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS chunks (
    id SERIAL PRIMARY KEY,
    document_uuid TEXT NOT NULL,
    chunk_index INT NOT NULL,
    content TEXT NOT NULL,
    embedding VECTOR(1024)
);

CREATE INDEX IF NOT EXISTS chunks_embedding_idx 
ON chunks USING hnsw (embedding vector_cosine_ops);
```

### 4. Генерация UUID для заметок

Перед первой индексацией убедитесь, что у всех `.md` файлов в вашем хранилище есть `uuid` в свойствах (frontmatter). Запустите скрипт:

```bash
python norm_rag/id_genchik.py
```

### 5. Индексация базы знаний

Запустите процесс векторизации заметок (при первом запуске скачается модель `multilingual-e5-large`):

```bash
python norm_rag/indexer.py
```

### 6. Запуск поиска и чата

Запустите интерактивного ассистента:

```bash
python norm_rag/searcher.py
```
Для выхода из режима чата введите `exit` или `quit`.

---

## 📄 Лицензия

Проект распространяется под лицензией MIT.

# TODO
- надо каким-то хитрым сделать чанки(векторизованный кусок текста) более менее осмысленными
- т.к. есть ограничения на запросы к конкретным моделям по gemini, надо встроить авто переход по моделям при достижении лимитов