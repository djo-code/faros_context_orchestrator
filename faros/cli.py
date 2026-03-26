import argparse
import sys
import subprocess
import logging

from faros.core.init_db import initialize_database
from faros.core.ingestion import ingest_markdown_to_vector
from faros.core.optimizer_rules import run_optimization_pipeline
from faros.core.optimizer_sei import run_sei_optimization

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

def main():
    parser = argparse.ArgumentParser(
        description="Faros Context Orchestrator: Unified DevFinOps Intelligence CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Usage Examples:
  faros init              # Initialize DuckDB schema
  faros optimize-rules    # Run DSPy hardening on principles
  faros optimize-events --file <path_to_json>   # Transform raw SEI JSON to Markdown
  faros ingest            # Sync markdown_files/ to Vector DB
  faros server            # Launch the FastMCP Context Server
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Available Commands")

    subparsers.add_parser("init", help="Initialize the DuckDB database and schemas")
    subparsers.add_parser("optimize-rules", help="Execute DSPy pipeline to harden engineering principles")
    
    events_parser = subparsers.add_parser("optimize-events", help="Transform raw SEI event JSON into vector-optimized Markdown")
    events_parser.add_argument("--file", "-f", required=True, help="Path to the JSON SEI event payload")

    subparsers.add_parser("ingest", help="Vectorize and ingest Markdown files into the HNSW index")
    subparsers.add_parser("server", help="Start the Faros FastMCP Server for Claude Desktop")

    args = parser.parse_args()

    if args.command == "init":
        logger.info("🛠️  Initializing Faros Database...")
        initialize_database()

    elif args.command == "optimize-rules":
        logger.info("🧠 Running DSPy Rule Hardening...")
        run_optimization_pipeline()

    elif args.command == "optimize-events":
        logger.info(f"📊 Processing SEI Event Payload from {args.file}...")
        run_sei_optimization(args.file)

    elif args.command == "ingest":
        logger.info("📥 Ingesting context into Vector Store...")
        ingest_markdown_to_vector()

    elif args.command == "server":
        logger.info("🚀 Launching Faros Context Orchestrator Server...")
        try:
            # Run using the python module path to cleanly isolate the process
            subprocess.run([sys.executable, "-m", "faros.server"], check=True)
        except KeyboardInterrupt:
            logger.info("\n👋 Server stopped.")
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Server failed to start: {e}")

    else:
        parser.print_help()
        sys.exit(1)

if __name__ == "__main__":
    main()