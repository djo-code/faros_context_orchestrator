import dspy
import duckdb
import re
import os
import logging
from dspy.teleprompt import BootstrapFewShot
from faros.config import DB_PATH, MARKDOWN_DIR

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# 1. Setup Claude 4.6
claude = dspy.LM('anthropic/claude-sonnet-4-6', max_tokens=4096)
dspy.settings.configure(lm=claude)

# --- SIGNATURES ---

class CodeGeneration(dspy.Signature):
    """Write Python code that strictly adheres to an engineering principle."""
    principle_description = dspy.InputField(desc="The core engineering rule")
    code = dspy.OutputField(desc="Python code demonstrating the rule")

class Evaluation(dspy.Signature):
    """Critique the code based on a specific engineering principle."""
    principle = dspy.InputField()
    code = dspy.InputField()
    adheres_to_rule = dspy.OutputField(desc="True/False")
    critique = dspy.OutputField(desc="A technical critique of the implementation")

class GenerateVectorRule(dspy.Signature):
    """
    Generate a structured Markdown rule optimized for VectorDB retrieval. The retrieval will happen when a coding agent asks for context via an MCP server.
    Ensure high semantic density for embeddings. Include:
    - Metadata Header
    - Core Constraint
    - Negative Patterns (What to avoid)
    - Positive Pattern (The fix)
    """
    principle_name = dspy.InputField()
    principle_description = dspy.InputField()
    critique = dspy.InputField(desc="The evaluation feedback from the tech lead")
    code_example = dspy.InputField(desc="A validated code snippet")
    markdown_rule = dspy.OutputField(desc="Structured Markdown for VectorDB ingestion")

# --- MODULE ---

class FarosRuleOptimizer(dspy.Module):
    def __init__(self):
        super().__init__()
        self.generate = dspy.ChainOfThought(CodeGeneration)
        self.evaluate = dspy.ChainOfThought(Evaluation)
        self.synthesize = dspy.Predict(GenerateVectorRule) # Final distillation step

    def forward(self, principle_name, principle_description):
        # 1. Actor: Generate code
        prediction = self.generate(principle_description=principle_description)
        
        # 2. Critic: Evaluate code
        eval_res = self.evaluate(
            principle=principle_name, 
            code=prediction.code
        )
        
        # 3. Architect: Synthesize the final Vector-Optimized Rule
        final_rule = self.synthesize(
            principle_name=principle_name,
            principle_description=principle_description,
            critique=eval_res.critique,
            code_example=prediction.code
        )
        
        return dspy.Prediction(
            markdown=final_rule.markdown_rule,
            adheres=eval_res.adheres_to_rule
        )

# --- UTILS ---

def normalize_input(input_str):
    clean_name = re.sub(r'[^a-zA-Z0-9]+', ' ', input_str)
    return re.sub(r'\s+', '_', clean_name.strip()).lower()

def faros_metric(gold, pred, trace=None):
    return str(pred.adheres).lower() in ['true', 'yes', 'pass']

# --- EXECUTION ---

def run_optimization_pipeline():
    conn = duckdb.connect(str(DB_PATH))
    try:
        df = conn.execute("SELECT principle, description FROM engineering_principles").df()
    except Exception as e:
        logger.error(f"Failed to query engineering_principles table from {DB_PATH}: {e}")
        conn.close()
        return
    conn.close()

    if df.empty:
        logger.warning("No engineering principles found to optimize. Database may need seeding.")
        return

    trainset = [
        dspy.Example(
            principle_name=row['principle'], 
            principle_description=row['description']
        ).with_inputs('principle_name', 'principle_description')
        for _, row in df.iterrows()
    ]

    config = BootstrapFewShot(metric=faros_metric, max_labeled_demos=2, max_bootstrapped_demos=2)
    optimizer = config.compile(FarosRuleOptimizer(), trainset=trainset)
    
    for example in trainset:
        logger.info(f"🔄 Hardening Principle: {example.principle_name}...")
        
        result = optimizer(
            principle_name=example.principle_name, 
            principle_description=example.principle_description
        )
        
        file_name = f"{normalize_input(example.principle_name)}.md"
        output_path = MARKDOWN_DIR / file_name
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(result.markdown)
            
    logger.info("✅ Faros Context Engine: All principles optimized and saved.")

if __name__ == "__main__":
    run_optimization_pipeline()