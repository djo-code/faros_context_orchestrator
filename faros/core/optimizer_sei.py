import dspy
import json
import os
import re
import logging
from faros.config import MARKDOWN_DIR

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# 1. Setup Claude 4.6
claude = dspy.LM('anthropic/claude-sonnet-4-6', max_tokens=4096)
dspy.settings.configure(lm=claude)

# --- SIGNATURES ---

class SEIAnalysis(dspy.Signature):
    """Analyze a raw SEI webhook JSON and extract the business narrative."""
    raw_json = dspy.InputField(desc="The raw event payload from Jira/GitHub")
    business_narrative = dspy.OutputField(desc="A summary of the effort, velocity, and capitalized cost")

class SEIEvaluation(dspy.Signature):
    """Evaluate if the narrative accurately reflects the JSON metrics without hallucination."""
    raw_json = dspy.InputField()
    business_narrative = dspy.InputField()
    is_accurate = dspy.OutputField(desc="True or False")
    critique = dspy.OutputField(desc="Technical critique of FinOps and DORA metric accuracy")

class GenerateSEIMarkdown(dspy.Signature):
    """
    Generate a structured Markdown file optimized for VectorDB retrieval.
    Must include:
    - Task Metadata (ID, Team, Dev)
    - FinOps Capitalization (Cost Center, CAPEX/OPEX, USD)
    - DORA/Velocity Metrics (Cycle Time, Rework)
    - Semantic Summary for the embedding model
    """
    raw_json = dspy.InputField()
    critique = dspy.InputField(desc="Feedback from the FinOps evaluator")
    markdown_report = dspy.OutputField(desc="Structured Markdown optimized for vector ingestion")

# --- MODULE ---

class FarosSEIOptimizer(dspy.Module):
    def __init__(self):
        super().__init__()
        self.analyze = dspy.ChainOfThought(SEIAnalysis)
        self.evaluate = dspy.ChainOfThought(SEIEvaluation)
        self.synthesize = dspy.Predict(GenerateSEIMarkdown)

    def forward(self, raw_json):
        # 1. Analyst: Draft the narrative
        analysis = self.analyze(raw_json=raw_json)
        
        # 2. Auditor: Check the math and tags
        eval_res = self.evaluate(raw_json=raw_json, business_narrative=analysis.business_narrative)
        
        # 3. Architect: Generate the Vector-Ready Markdown
        final_md = self.synthesize(
            raw_json=raw_json,
            critique=eval_res.critique
        )
        
        return dspy.Prediction(
            markdown=final_md.markdown_report,
            adheres=eval_res.is_accurate
        )

# --- EXECUTION ---

def run_sei_optimization(sei_event_filepath: str):
    if not os.path.exists(sei_event_filepath):
        logger.error(f"Task payload file not found: {sei_event_filepath}")
        return

    with open(sei_event_filepath, "r", encoding="utf-8") as f:
        try:
            sei_event = json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON string: {e}")
            return

    json_str = json.dumps(sei_event, indent=2)
    task_id = sei_event.get("data", {}).get("task_id", "unknown_task")
    logger.info(f"🔄 Processing SEI Event: {task_id}...")
    
    optimizer = FarosSEIOptimizer()
    result = optimizer(raw_json=json_str)
    
    file_name = f"sei_event_{task_id.lower().replace('-', '_')}.md"
    output_path = MARKDOWN_DIR / file_name
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(result.markdown)
        
    logger.info(f"✅ Generated SEI Markdown: {output_path}")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        run_sei_optimization(sys.argv[1])
    else:
        logger.error("Please provide the path to an SEI event JSON file.")