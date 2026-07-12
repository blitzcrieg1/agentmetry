"""MITRE ATT&CK mappings for agent tools."""

from __future__ import annotations

# Basic mappings for common tools used by AI agents
MITRE_MAPPINGS = {
    # Execution
    "os.run_command": {"tactic": "Execution (TA0002)", "technique": "Command and Scripting Interpreter (T1059)"},
    "shell.run": {"tactic": "Execution (TA0002)", "technique": "Command and Scripting Interpreter (T1059)"},
    "bash": {"tactic": "Execution (TA0002)", "technique": "Command and Scripting Interpreter (T1059)"},
    
    # Collection
    "vault_fs.read_file": {"tactic": "Collection (TA0009)", "technique": "Data from Local System (T1005)"},
    "os.read_file": {"tactic": "Collection (TA0009)", "technique": "Data from Local System (T1005)"},
    "str_replace_editor.view": {"tactic": "Collection (TA0009)", "technique": "Data from Local System (T1005)"},
    
    # Impact / Data Manipulation
    "vault_fs.write_file": {"tactic": "Impact (TA0040)", "technique": "Data Destruction/Manipulation (T1485/T1565)"},
    "os.write_file": {"tactic": "Impact (TA0040)", "technique": "Data Destruction/Manipulation (T1485/T1565)"},
    "str_replace_editor.edit": {"tactic": "Impact (TA0040)", "technique": "Data Destruction/Manipulation (T1485/T1565)"},
    
    # Discovery
    "vault_fs.list_dir": {"tactic": "Discovery (TA0007)", "technique": "File and Directory Discovery (T1083)"},
    "os.list_dir": {"tactic": "Discovery (TA0007)", "technique": "File and Directory Discovery (T1083)"},
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
