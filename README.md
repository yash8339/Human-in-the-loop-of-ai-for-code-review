# Human-in-the-Loop AI Code Review

## Problem statement

Traditional code review depends heavily on reviewer availability and experience. Static analyzers can identify known patterns, but they may miss context and produce tool-specific output. AI reviewers can explain possible problems, but their suggestions need validation because they may be incomplete or incorrect.

This project combines automated analysis with human judgment. It is designed to help reviewers find security and quality issues faster while keeping the final decision with a human reviewer.

## Project approach

The application follows this workflow:

```text
User code
	 |
	 +--> AI reviewer ----------------+
	 |    OpenAI, Gemini, Groq, Claude |
	 |                                |
	 +--> Static analysis ------------+--> Finding comparison
				Semgrep, Bandit                    |
																					 v
																		Human validation
																					 |
																					 v
																		 Final report
```

1. The user submits source code through the Flask web interface.
2. The selected AI provider reviews the code and returns structured findings.
3. Semgrep or Bandit performs static analysis and returns structured findings.
4. The merge logic compares findings from the different sources.
5. A human accepts, rejects, or modifies each review finding.
6. The application stores the review and displays a final report with evaluation metrics.

The supported finding formats are:

AI review:

```json
{
	"line": 5,
	"issue_type": "command-execution",
	"description": "A shell command is executed with user-controlled input.",
	"suggested_fix": "Use a safe API and validate the input."
}
```

Static analysis:

```json
{
	"line": 5,
	"rule_id": "B602",
	"severity": "high",
	"message": "subprocess call with shell=True identified."
}
```

## Project layout

```text
Human-in-the-loop-of-ai-for-code-review/
├── project/
│   ├── backend/
│   │   ├── main.py                  # Flask application
│   │   ├── ai_review/               # AI provider adapters
│   │   │   ├── base.py
│   │   │   ├── claude.py
│   │   │   ├── gemini.py
│   │   │   ├── groq.py
│   │   │   ├── openai.py
│   │   │   └── reviewer.py
│   │   ├── static_analysis/         # Semgrep and Bandit
│   │   ├── merge/                   # Finding comparison
│   │   ├── human_review/            # Human decisions
│   │   ├── utils/schema.py          # Shared result schemas
│   │   ├── review_engine.py         # Review orchestration
│   │   └── evaluation.py            # Metrics
│   ├── frontend/templates/          # Flask HTML templates
│   ├── tests/                       # Automated tests
│   │   ├── fixtures/                # Sample Python files used by tests
│   │   │   ├── benign_code.py
│   │   │   ├── dynamic_code.py
│   │   │   └── unsafe_code.py
│   │   ├── test_ai_providers.py
│   │   ├── test_merge_logic.py
│   │   ├── test_review_engine.py
│   │   └── test_reviewer_modules.py
│   └── requirements.txt
└── README.md
```

## File format

The current review engine supports Python source code (`.py`) for AI and static analysis. The web form accepts the source as text and stores the selected filename as metadata. A typical submission is:

```python
import subprocess

subprocess.call(user_command, shell=True)
```

The system creates temporary `.py` files internally when analyzing submitted code. Findings are returned as JSON-like Python dictionaries and are converted into the application result model before being stored in MySQL.

## Requirements

- Python 3.10 or newer
- Flask
- MySQL server for registration, uploads, reviews, and reports
- Semgrep and Bandit for static analysis
- Optional API key for the selected AI provider

Install dependencies from the `project` directory:

```powershell
pip install -r requirements.txt
```

## Run the website

From the repository root:

```powershell
cd project
.\.venv\Scripts\Activate.ps1
python backend\main.py
```

Open the website at:

```text
http://127.0.0.1:5000
```

Press `Ctrl+C` in the terminal to stop the server.

## Configure AI providers

Set the key for the provider selected in the dashboard. The supported variables are:

```powershell
$env:OPENAI_API_KEY = "your-key"
$env:GEMINI_API_KEY = "your-key"
$env:GROQ_API_KEY = "your-key"
$env:ANTHROPIC_API_KEY = "your-key"
```

Optional model and endpoint variables are also supported:

- `OPENAI_MODEL`, `OPENAI_API_URL`
- `GEMINI_MODEL`, `GEMINI_API_URL`
- `GROQ_MODEL`, `GROQ_API_URL`
- `ANTHROPIC_MODEL`, `ANTHROPIC_API_URL`

If the selected provider has no key or the request fails, the local fallback detects the sample Python security patterns so the application can still be used offline.

## Run tests

From the repository root:

```powershell
project\.venv\Scripts\python.exe -m pytest project/tests -q
```

The tests cover static analysis, AI response normalization, all four provider adapters using mocked responses, merge logic, human decisions, and review orchestration.