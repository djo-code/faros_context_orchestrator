import os
import logging
import duckdb
from sentence_transformers import SentenceTransformer
from faros.config import DB_PATH, MARKDOWN_DIR

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

logger.info("Loading SentenceTransformer model...")
model = SentenceTransformer('all-MiniLM-L6-v2')

def ingest_markdown_to_vector():
    """Reads markdown optimized rules and ingests them into the VectorDB."""
    try:
        conn = duckdb.connect(str(DB_PATH))
        conn.execute("LOAD vss;")
        conn.execute("SET hnsw_enable_experimental_persistence = true;")
        
        if not MARKDOWN_DIR.exists():
            logger.error(f"Error: {MARKDOWN_DIR} directory not found.")
            return

        files_processed = 0
        for file_path in MARKDOWN_DIR.glob("*.md"):
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            principle_id = file_path.stem
            embedding = model.encode(content).tolist()
            
            conn.execute("""
                INSERT OR REPLACE INTO faros_vector_store (principle_id, content, embedding)
                VALUES (?, ?, ?)
            """, [principle_id, content, embedding])
            
            logger.info(f"✅ Ingested: {principle_id}")
            files_processed += 1

        conn.close()
        logger.info(f"🚀 Ingestion Complete. {files_processed} records embedded.")
    except Exception as e:
        logger.error(f"❌ Ingestion failed: {e}")
        raise

if __name__ == "__main__":
    ingest_markdown_to_vector()