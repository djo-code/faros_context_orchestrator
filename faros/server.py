import sys
import yaml
import logging
import duckdb
from mcp.server.fastmcp import FastMCP
from sentence_transformers import SentenceTransformer
from faros.config import DB_PATH, MACRO_YAML_PATH

logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

mcp = FastMCP("Faros Context Orchestrator")

logger.info("Loading SentenceTransformer model (all-MiniLM-L6-v2)...")
model = SentenceTransformer('all-MiniLM-L6-v2')

def load_macro_context() -> str:
    """Loads strategic business directives from a YAML file."""
    try:
        if not MACRO_YAML_PATH.exists():
            return "Warning: macro_context.yaml not found. Proceeding with default directives."
            
        with open(MACRO_YAML_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            directives = data.get("strategic_engineering_directives", {})
            
            macro_str = "### [TIER 1] FAROS MACRO BUSINESS DIRECTIVES ###\n"
            macro_str += "As a Faros engineer, all code must align with these product pillars:\n"
            
            for key, rules in directives.items():
                formatted_key = key.replace('_', ' ').title()
                for rule in rules:
                    macro_str += f"- **{formatted_key}**: {rule}\n"
            
            return macro_str
    except Exception as e:
        logger.error(f"Error loading YAML: {str(e)}")
        return f"Warning: Could not load macro_context.yaml: {str(e)}"

GLOBAL_MACRO_CONTEXT = load_macro_context()

@mcp.tool()
def search_faros_knowledge_base(search_query: str) -> str:
    """
    CRITICAL: Your training data does not contain Faros coding standards. You MUST use this tool first. Search for the core concepts (e.g., "effort tracking 
    rules" or "capitalized investments") before providing your code review.
    
    Searches the proprietary Faros Knowledge Base for internal engineering standards, 
    DevFinOps rules, and historical SEI event data.
    """
    try:
        query_vector = model.encode(search_query).tolist()
        
        conn = duckdb.connect(str(DB_PATH))
        conn.execute("LOAD vss;")
        conn.execute("SET hnsw_enable_experimental_persistence = true;")
        
        query = """
            SELECT principle_id, content, array_cosine_similarity(embedding, ?::FLOAT[384]) AS score
            FROM faros_vector_store
            ORDER BY score DESC
            LIMIT 1;
        """
        
        result = conn.execute(query, [query_vector]).fetchone()
        conn.close()
        
        if result and result[2] > 0.45:
            principle_id, content, score = result
            return (
                f"{GLOBAL_MACRO_CONTEXT}\n\n"
                f"### [TIER 3] SPECIFIC ENGINEERING CONSTRAINT (Confidence: {score:.2f}) ###\n"
                f"Rule triggered: '{principle_id}'\n\n"
                f"{content}\n\n"
                f"--- \n"
                f"**INSTRUCTION:** Refactor the user's code to satisfy BOTH the Tier 3 constraint and the Tier 1 macro directives."
            )
        else:
            return (
                f"{GLOBAL_MACRO_CONTEXT}\n\n"
                "### [TIER 3] SPECIFIC ENGINEERING CONSTRAINT ###\n"
                "No specific low-level syntax principles triggered. Proceed with refactoring while strictly enforcing the Tier 1 Macro Directives."
            )

    except Exception as e:
        logger.error(f"Tool execution error: {str(e)}")
        return f"Faros Context Engine Error: {str(e)}"

if __name__ == "__main__":
    mcp.run()