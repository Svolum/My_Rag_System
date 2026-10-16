import sqlite3
import uuid
import re
import logging
from pathlib import Path
from typing import Optional

# Настройка базового логирования для отслеживания процесса
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


class UuidManager:
    """Управляет сохранением и получением UUID через SQLite."""

    def __init__(self, db_path: Path):
        self.conn = sqlite3.connect(db_path)
        self._init_db()

    def _init_db(self) -> None:
        with self.conn:
            self.conn.execute("""
                              CREATE TABLE IF NOT EXISTS file_uuids
                              (
                                  file_path
                                  TEXT
                                  PRIMARY
                                  KEY,
                                  uuid
                                  TEXT
                                  UNIQUE
                                  NOT
                                  NULL,
                                  assigned_at
                                  TIMESTAMP
                                  DEFAULT
                                  CURRENT_TIMESTAMP
                              )
                              """)

    def save_mapping(self, file_path: str, file_uuid: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO file_uuids (file_path, uuid) VALUES (?, ?)",
                (file_path, file_uuid)
            )

    def close(self) -> None:
        self.conn.close()


def process_markdown_file(file_path: Path, db_manager: UuidManager) -> bool:
    """
    Добавляет UUID в начало Markdown файла.
    Возвращает True, если файл был изменен, и False, если пропущен.
    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except PermissionError:
        logging.error(f"Нет прав на чтение: {file_path}")
        return False
    except UnicodeDecodeError:
        logging.error(f"Ошибка кодировки (не UTF-8): {file_path}")
        return False

    # Крайний случай 1: UUID уже существует в файле
    if re.search(r'^---\r?\n.*?\buuid:\s*[a-f0-9\-]+\b', content, re.DOTALL | re.IGNORECASE):
        logging.debug(f"Пропущен (UUID уже есть): {file_path.name}")
        return False

    new_uuid = str(uuid.uuid4())

    # Крайний случай 2: У файла уже есть YAML frontmatter, но без UUID.
    # Нужно аккуратно внедрить ключ после первого '---', не ломая остальную структуру.
    if content.startswith("---"):
        new_content = re.sub(
            r'^---\r?\n',
            f'---\nuuid: {new_uuid}\n',
            content,
            count=1
        )
    # Крайний случай 3: Файл пустой или начинается сразу с текста.
    # Создаем новый блок YAML.
    else:
        new_content = f'---\nuuid: {new_uuid}\n---\n{content}'

    try:
        file_path.write_text(new_content, encoding="utf-8")
        # Сохраняем в БД только после успешной записи на диск
        # as_posix() стандартизирует пути (слэши) между Windows и Linux
        db_manager.save_mapping(file_path.as_posix(), new_uuid)
        logging.info(f"Добавлен UUID в {file_path.name}")
        return True
    except PermissionError:
        logging.error(f"Нет прав на запись: {file_path}")
        return False


def main(target_directory: str | Path, db_filename: str = "uuid_mapping.db") -> None:
    target_path = Path(target_directory).resolve()

    if not target_path.exists() or not target_path.is_dir():
        logging.error(f"Директория не найдена: {target_path}")
        return

    db_path = target_path / db_filename
    db_manager = UuidManager(db_path)

    modified_count = 0
    error_count = 0

    logging.info(f"Начало сканирования директории: {target_path}")

    try:
        # rglob("*.md") рекурсивно ищет все .md файлы в текущей и вложенных папках
        for md_file in target_path.rglob("*.md"):
            try:
                if process_markdown_file(md_file, db_manager):
                    modified_count += 1
            except Exception as e:
                logging.error(f"Критическая ошибка при обработке {md_file.name}: {e}")
                error_count += 1
    finally:
        db_manager.close()

    logging.info(f"Готово. Изменено файлов: {modified_count}. Ошибок: {error_count}.")


if __name__ == "__main__":
    # Укажи здесь путь к своей директории, например: r"C:\Users\Name\Obsidian\Notes"
    # или "." для запуска в текущей папке.
    DIRECTORY_TO_SCAN = "C:\programs\my_obsidian\my_vaults\MyVault"
    main(DIRECTORY_TO_SCAN)
