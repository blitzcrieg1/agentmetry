"""MITRE ATT&CK mappings for agent tools."""

from __future__ import annotations

# Basic mappings for common tools used by AI agents
MITRE_MAPPINGS = {
    # Execution
    "run_command": {"tactic": "Execution (TA0002)", "technique": "Command and Scripting Interpreter (T1059)"},
    "shell.run": {"tactic": "Execution (TA0002)", "technique": "Command and Scripting Interpreter (T1059)"},
    "bash": {"tactic": "Execution (TA0002)", "technique": "Command and Scripting Interpreter (T1059)"},
    
    # Collection
    "read_file": {"tactic": "Collection (TA0009)", "technique": "Data from Local System (T1005)"},
    "view_file": {"tactic": "Collection (TA0009)", "technique": "Data from Local System (T1005)"},
    "grep_search": {"tactic": "Collection (TA0009)", "technique": "Data from Local System (T1005)"},
    
    # Impact / Data Manipulation
    "write_file": {"tactic": "Impact (TA0040)", "technique": "Data Destruction/Manipulation (T1485/T1565)"},
    "write_to_file": {"tactic": "Impact (TA0040)", "technique": "Data Destruction/Manipulation (T1485/T1565)"},
    "replace_file_content": {"tactic": "Impact (TA0040)", "technique": "Data Destruction/Manipulation (T1485/T1565)"},
    "multi_replace_file_content": {"tactic": "Impact (TA0040)", "technique": "Data Destruction/Manipulation (T1485/T1565)"},
    
    # Discovery
    "list_dir": {"tactic": "Discovery (TA0007)", "technique": "File and Directory Discovery (T1083)"},
}

def get_mitre_mapping(tool_name: str) -> dict[str, str] | None:
    """Return the MITRE tactic and technique for a given tool name."""
    # Try exact match
    if tool_name in MITRE_MAPPINGS:
        return MITRE_MAPPINGS[tool_name]
    
    # Try generic fallback (e.g. 'read_file' matches 'vault_fs.read_file')
    for key, mapping in MITRE_MAPPINGS.items():
        if tool_name.endswith(key) or key.endswith(tool_name):
            return mapping
            
    return None
