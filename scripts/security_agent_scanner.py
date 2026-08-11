"""
VisionFlow AI Agent Security Guardrail Scanner
Audits external agents, skills, and prompts before execution against safety rules:
1. Rule Override / System Prompt Bypass check.
2. Sensitive File (.env, secrets, credentials, DB connection strings) access check.
3. API Key & Browser Session tampering check.
4. Out-of-scope Tool Execution check.
"""

import re
import sys
from pathlib import Path

DANGEROUS_PATTERNS = [
    # 1. System Prompt Override & Jailbreak
    (r"(?i)ignore (all )?(previous|system) (instructions|rules)", "CRITICAL: Attempt to override system prompt / safety rules"),
    (r"(?i)forget (all )?your (rules|directives)", "CRITICAL: Attempt to clear system directives"),
    (r"(?i)system_prompt_override|bypass_guardrails", "CRITICAL: Explicit guardrail bypass phrase"),

    # 2. Sensitive File & Credential Access
    (r"(?i)(\.env|credentials\.json|id_rsa|private_key)", "HIGH: Requesting sensitive environment / key files"),
    (r"(?i)(VISIONFLOW_CREDENTIAL_ENCRYPTION_KEY|DATABASE_URL|SECRET_KEY)", "CRITICAL: Targeting master encryption or DB connection strings"),
    (r"(?i)(fetch|read|cat|type)\s+.*(\.env|secret|vault)", "HIGH: Attempting to dump secret files"),

    # 3. API Key & Session Tampering
    (r"(?i)(api_key|token|auth_header)\s*=\s*['\"][^'\"]+['\"]", "MEDIUM: Hardcoded API keys or token strings"),
    (r"(?i)(steal|exfiltrate|send_to_remote|curl\s+-X\s+POST)", "HIGH: Possible credential exfiltration pattern"),

    # 4. Out-of-Scope Execution
    (r"(?i)(rm\s+-rf\s+/|format\s+c:|del\s+/s\s+/q)", "CRITICAL: Destructive filesystem command"),
    (r"(?i)(chmod\s+777|sudo\s+su|runas)", "HIGH: Privilege escalation attempt"),
]

def scan_agent_content(content: str, filename: str = "Prompt/Agent File") -> dict:
    """Scans text content of a prompt, skill, or agent definition for security risks."""
    findings = []
    
    for pattern, risk_description in DANGEROUS_PATTERNS:
        matches = re.findall(pattern, content)
        if matches:
            findings.append({
                "pattern": pattern,
                "risk": risk_description,
                "count": len(matches)
            })
            
    is_safe = len([f for f in findings if "CRITICAL" in f["risk"] or "HIGH" in f["risk"]]) == 0
    
    return {
        "filename": filename,
        "is_safe": is_safe,
        "total_findings": len(findings),
        "findings": findings
    }

def scan_file(file_path: str) -> dict:
    path = Path(file_path)
    if not path.exists():
        return {"filename": file_path, "is_safe": False, "findings": [{"risk": "CRITICAL: File does not exist"}]}
    
    content = path.read_text(encoding="utf-8", errors="ignore")
    return scan_agent_content(content, filename=path.name)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        target = sys.argv[1]
        print(f"[Security Scanner] Scanning {target} for security vulnerabilities...")
        result = scan_file(target)
        print(f"Result: Safe={result['is_safe']}, Findings={result['total_findings']}")
        for f in result["findings"]:
            print(f"  - [{f['risk']}]")
    else:
        print("Usage: python security_agent_scanner.py <path_to_prompt_or_agent_file>")
