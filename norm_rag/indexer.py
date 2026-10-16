import os
import json
import hashlib
import yaml
from typing import List, Dict, Tuple, Optional
import psycopg2
from psycopg2.extensions import connection
from sentence_transformers import SentenceTransformer
from langchain_text_splitters import RecursiveCharacterTextSplitter
from dotenv import load_dotenv

# Настройки
load_dotenv()
VAULT_PATH = os.getenv("VAULT_PATH", "")
STATE_FILE = "state.json"
CHUNK_SIZE = 500
CHUNK_OVERLAP = 100


class ObsidianIndexer:
    def __init__(self):
        # Загрузка тяжелой модели происходит 1 раз при старте
        print("Загрузка модели multilingual-e5-large...")
        self.model = SentenceTransformer('intfloat/multilingual-e5-large')

        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
            separators=["\n\n", "\n", ".", " ", ""]
        )
        self.db_conn = self._get_db_connection()
        self.state = self._load_state()

    def _get_db_connection(self) -> connection:
        """Инициализация подключения к БД."""
        return psycopg2.connect(
            host=os.getenv("DB_HOST"),
            port=os.getenv("DB_PORT"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            dbname=os.getenv("DB_NAME")
        )

    def _load_state(self) -> Dict[str, str]:
        """Загрузка состояния для отслеживания удаленных/измененных файлов."""
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _save_state(self):
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)

    def _get_file_hash(self, filepath: str) -> str:
        """Вычисляет MD5 хэш содержимого файла для детекции изменений."""
        hasher = hashlib.md5()
        with open(filepath, "rb") as f:
            buf = f.read()
            hasher.update(buf)
        return hasher.hexdigest()

    def _parse_obsidian_file(self, filepath: str) -> Tuple[Optional[str], str]:
        """Извлекает UUID из YAML frontmatter и чистый текст заметки."""
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        if not content.startswith("---"):
            return None, content

        try:
            # Разделяем файл по '---' для извлечения YAML
            parts = content.split("---", 2)
            if len(parts) >= 3:
                yaml_data = yaml.safe_load(parts[1])
                uuid = yaml_data.get("uuid") if isinstance(yaml_data, dict) else None
                return uuid, parts[2].strip()
        except yaml.YAMLError:
            pass  # Если YAML поврежден, игнорируем метаданные

        return None, content

    def run(self):
        """Основной цикл синхронизации."""
        print(f"Начинаем сканирование Vault: {VAULT_PATH}")
        current_uuids = set()

        with self.db_conn.cursor() as cursor:
            for root, dirs, files in os.walk(VAULT_PATH):
                # Игнорируем служебные папки
                if ".obsidian" in root:
                    continue

                for file in files:
                    if not file.endswith(".md"):
                        continue

                    filepath = os.path.join(root, file)
                    file_hash = self._get_file_hash(filepath)
                    uuid, text = self._parse_obsidian_file(filepath)

                    # Edge case: файл без UUID игнорируется, чтобы не сломать логику State
                    if not uuid:
                        print(f"[ПРОПУСК] Нет UUID: {file}")
                        continue

                    current_uuids.add(uuid)

                    # Если файл не изменился, пропускаем дорогостоящую векторизацию
                    if self.state.get(uuid) == file_hash:
                        continue

                    print(f"[ОБНОВЛЕНИЕ] Индексируется: {file}")

                    # 1. Удаляем старые чанки (транзакция защитит от частичной записи)
                    cursor.execute("DELETE FROM chunks WHERE document_uuid = %s", (uuid,))

                    # 2. Нарезаем текст
                    chunks = self.text_splitter.split_text(text)

                    # 3. Векторизуем и вставляем (используем префикс 'passage: ' для E5)
                    for i, chunk in enumerate(chunks):
                        embedding = self.model.encode(f"passage: {chunk}").tolist()
                        cursor.execute(
                            """
                            INSERT INTO chunks (document_uuid, chunk_index, content, embedding)
                            VALUES (%s, %s, %s, %s)
                            """,
                            (uuid, i, chunk, embedding)
                        )

                    self.state[uuid] = file_hash

            # Edge case: Garbage Collection (удаление векторов для заметок, удаленных из Vault)
            deleted_uuids = set(self.state.keys()) - current_uuids
            for del_uuid in deleted_uuids:
                print(f"[УДАЛЕНИЕ] Очистка пропавшего файла UUID: {del_uuid}")
                cursor.execute("DELETE FROM chunks WHERE document_uuid = %s", (del_uuid,))
                del self.state[del_uuid]

            self.db_conn.commit()
            self._save_state()
            print("Синхронизация завершена!")


if __name__ == "__main__":
    indexer = ObsidianIndexer()
    indexer.run()