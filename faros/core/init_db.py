import duckdb
import logging
import sys
import json
import os
from pathlib import Path
from faros.config import DB_PATH

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

def configure_claude_desktop():
    """Configures Claude Desktop to recognize the Faros MCP server."""
    config_path = Path.home() / "Library/Application Support/Claude/claude_desktop_config.json"
    
    config = {}
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read existing Claude config: {e}. Overwriting.")
            
    if "mcpServers" not in config:
        config["mcpServers"] = {}
        
    project_root = str(Path(__file__).resolve().parent.parent.parent)
    
    config["mcpServers"]["faros"] = {
        "command": sys.executable,
        "args": ["-m", "faros.cli", "server"],
        "env": {
            "PYTHONPATH": project_root,
            "PYTHONUNBUFFERED": "1"
        }
    }
    
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        logger.info("✅ Automatically configured Faros MCP Server in Claude Desktop.")
    except Exception as e:
        logger.error(f"❌ Failed to update Claude Desktop config: {e}")

principles_data = [
    # Code Quality & Maintainability
    ("Code Quality & Maintainability", "Don't Repeat Yourself (DRY)", "Maintain a single, unambiguous source of truth for every piece of knowledge or logic in your system to prevent synchronization bugs."),
    ("Code Quality & Maintainability", "Prioritize Readability", "Write code for humans first. Use clear, intention-revealing names for variables and functions so the code explains itself without needing excessive comments."),
    ("Code Quality & Maintainability", "Leave It Better Than You Found It", "Continuously clean up and refactor small messes as you work to prevent long-term architectural degradation (the Boy Scout Rule)."),
    
    # Design & Complexity Management
    ("Design & Complexity Management", "Build Deep Modules", "Create components and classes that offer simple, narrow interfaces to the outside world while hiding complex internal implementations."),
    ("Design & Complexity Management", "Enforce Single Responsibility", "Ensure that functions, classes, and services do exactly one thing, and do it well, to keep them easy to test and replace."),
    ("Design & Complexity Management", "Design for Orthogonality", "Structure your system so that changing one component does not cause unintended side effects in completely unrelated areas."),
    ("Design & Complexity Management", "Invest Strategically", "Prioritize long-term design health and clean architecture over tactical, quick-and-dirty fixes that accumulate crippling technical debt."),
    
    # Architecture & Distributed Systems
    ("Architecture & Distributed Systems", "Embrace Trade-offs", "Accept that there is no perfect architecture. Every structural decision is simply a balance of competing characteristics like scalability, maintainability, cost, and performance."),
    ("Architecture & Distributed Systems", "Assume the Network Will Fail", "Never assume zero latency, infinite bandwidth, or perfect reliability. Always build in resilience, retries, and fallback mechanisms."),
    ("Architecture & Distributed Systems", "Align with Business Boundaries", "Structure microservices and system components around distinct business domains (Bounded Contexts) rather than technical layers to reduce friction as the business scales."),
    ("Architecture & Distributed Systems", "Ensure Independent Deployability", "Design distributed services so they can be modified, tested, and deployed entirely independently. If they must be deployed together, they are too tightly coupled."),
    ("Architecture & Distributed Systems", "Decentralize Data", "Avoid sharing a single massive database across multiple autonomous services. Let each service manage its own data store to prevent bottlenecks and system-wide failures."),

    # Project Constraints (FAR-800)
    ("Project Constraints (FAR-800)", "Tenant-ID Partitioning", "All Kafka topics must be partitioned by tenant_id to ensure strict data isolation and prevent 'noisy-neighbor' performance degradation."),
    ("Project Constraints (FAR-800)", "Asynchronous Analytics", "Heavy analytical joins (e.g., Cloud Billing to Jira) must be offloaded to an async Snowflake connector to prevent Postgres timeouts and dashboard lag."),
    ("Project Constraints (FAR-800)", "Decoupled Ingestion", "High-volume telemetry (webhooks) must be decoupled via a message broker (Kafka) to ensure zero data loss during peak CI/CD traffic."),
    ("Project Constraints (FAR-800)", "UI Library Governance", "New frontend components must utilize the internal Faros UI library (Tailwind + Radix UI) to maintain design consistency and reduce maintainability debt."),
    ("Project Constraints (FAR-800)", "Context-Aware Metrics", "Calculation engines (DORA metrics) must exclude weekends and holidays based on org_settings to provide accurate, human-centric data."),
    ("Project Constraints (FAR-800)", "Proactive Health Monitoring", "Correlate WIP limits, off-hours activity, and alert frequency to move from reactive reporting to proactive engineering burnout insights.")
]

def initialize_database():
    """Initializes the DuckDB database, installs extensions, and creates required schemas."""
    try:
        logger.info(f"Connecting to DuckDB at {DB_PATH}...")
        conn = duckdb.connect(str(DB_PATH))
        
        logger.info("Installing and loading VSS extension...")
        conn.execute("INSTALL vss;")
        conn.execute("LOAD vss;")
        conn.execute("SET hnsw_enable_experimental_persistence = true;")
        
        logger.info("Creating engineering_principles table (Source of Truth)...")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS engineering_principles (
                category VARCHAR,
                principle VARCHAR PRIMARY KEY,
                description TEXT
            );
        """)
        
        # Insert a seed row if table is empty, to prevent optimizer errors
        count = conn.execute("SELECT COUNT(*) FROM engineering_principles").fetchone()[0]
        if count == 0:
            logger.info("Seeding engineering_principles with core framework constraints...")
            conn.executemany("""
                INSERT INTO engineering_principles (category, principle, description) VALUES (?, ?, ?)
            """, principles_data)
        
        logger.info("Creating faros_vector_store table...")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS faros_vector_store (
                principle_id VARCHAR PRIMARY KEY,
                content TEXT,
                embedding FLOAT[384]
            );
        """)
        
        conn.execute("CREATE INDEX IF NOT EXISTS faros_idx ON faros_vector_store USING HNSW (embedding);")
        
        conn.close()
        logger.info("✅ Faros Context Database successfully initialized.")
        
        # Configure Claude Desktop
        configure_claude_desktop()
        
    except Exception as e:
        logger.error(f"❌ Failed to initialize database: {e}")
        raise

if __name__ == "__main__":
    initialize_database()