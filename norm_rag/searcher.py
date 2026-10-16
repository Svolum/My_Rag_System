import os
from typing import List, Tuple
import psycopg2
from sentence_transformers import SentenceTransformer
from google import genai
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from dotenv import load_dotenv

# Инициализация
load_dotenv()
console = Console()


class RAGSearcher:
    def __init__(self):
        console.print("[yellow]Загрузка локальной модели e5-large...[/yellow]")
        self.model = SentenceTransformer('intfloat/multilingual-e5-large')

        # Используем актуальный SDK 2026 года (google-genai)
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY не найден в .env. Создайте ключ в Google AI Studio.")
        self.gemini_client = genai.Client(api_key=api_key)

        self.db_conn = self._get_db_connection()

    def _get_db_connection(self):
        return psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("DB_PORT", "5433"),
            user=os.getenv("DB_USER", "rag_user"),
            password=os.getenv("DB_PASSWORD", "rag_password"),
            dbname=os.getenv("DB_NAME", "rag_db")
        )

    def retrieve_context(self, query: str, top_k: int = 1000) -> List[Tuple[str, float]]:
        """Ищет релевантные чанки в базе данных."""
        # Обязательный префикс для модели e5
        query_embedding = self.model.encode(f"query: {query}").tolist()
        # Преобразуем list в строку, понятную PostgreSQL (защита от ошибок адаптера psycopg2)
        query_embedding_str = f"[{','.join(map(str, query_embedding))}]"

        with self.db_conn.cursor() as cursor:
            # Оператор <=> вычисляет косинусное расстояние.
            cursor.execute(
                """
                SELECT content, (embedding <=> %s::vector) AS distance
                FROM chunks
                ORDER BY distance ASC
                    LIMIT %s
                """,
                (query_embedding_str, top_k)
            )
            return cursor.fetchall()

    def generate_answer(self, query: str, context_chunks: List[str]) -> str:
        """Формирует строгий промпт и делает запрос к LLM."""
        if not context_chunks:
            return "Я не нашел информации по этому вопросу в вашей базе заметок."

        context_text = "\n\n---\n\n".join(context_chunks)

        prompt = f"""Ты — полезный AI-ассистент. Твоя задача: ответить на вопрос пользователя, 
основываясь ТОЛЬКО на предоставленных ниже фрагментах из его личных заметок Obsidian. 
Не придумывай информацию. Если в заметках нет прямого ответа, честно скажи об этом.

КОНТЕКСТ (Заметки):
{context_text}

ВОПРОС: 
{query}
"""
        try:
            # Используем актуальную и быструю модель Gemini 2.5 Flash
            response = self.gemini_client.models.generate_content(
                model='gemini-3.6-flash',
                contents=prompt
            )
            return response.text
        except Exception as e:
            return f"Ошибка API Gemini: {str(e)}"

    def chat_loop(self):
        console.print(Panel.fit("RAG Система готова! Введите ваш вопрос (или 'exit' для выхода)", style="bold green"))

        while True:
            try:
                user_query = console.input("\n[bold cyan]Вы:[/bold cyan] ")
                if user_query.lower() in ['exit', 'quit', 'выход']:
                    break
                if not user_query.strip():
                    continue

                # 1. Поиск в БД (Retrieval)
                raw_results = self.retrieve_context(user_query)
                context_chunks = [row[0] for row in raw_results]

                console.print("[dim]Найдены релевантные заметки... Генерирую ответ...[/dim]")

                # 2. Генерация ответа (Generation)
                answer = self.generate_answer(user_query, context_chunks)

                # 3. Вывод Markdown интерфейсом rich
                console.print(Panel(Markdown(answer), title="Gemini", border_style="blue"))

            except KeyboardInterrupt:
                break
            except Exception as e:
                console.print(f"[bold red]Критическая ошибка:[/bold red] {e}")


if __name__ == "__main__":
    app = RAGSearcher()
    app.chat_loop()