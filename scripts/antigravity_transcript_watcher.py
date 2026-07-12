import os
import time
import json
import subprocess
import sys
from pathlib import Path

BRAIN_DIR = Path(os.path.expanduser("~/.gemini/antigravity/brain"))

def get_latest_transcript():
    if not BRAIN_DIR.exists():
        return None
    
    latest_file = None
    latest_time = 0
    
    for convo_dir in BRAIN_DIR.iterdir():
        if not convo_dir.is_dir():
            continue
        transcript_path = convo_dir / ".system_generated" / "logs" / "transcript.jsonl"
        if transcript_path.exists():
            mtime = transcript_path.stat().st_mtime
            if mtime > latest_time:
                latest_time = mtime
                latest_file = transcript_path
                
    return latest_file

def tail_file(file_path):
    print(f"Tailing {file_path}", flush=True)
    with open(file_path, "r", encoding="utf-8") as f:
        # Go to the end of the file
        f.seek(0, 2)
        while True:
            line = f.readline()
            if not line:
                time.sleep(0.5)
                yield None
                continue
            yield line

def process_line(line, conversation_id):
    if not line.strip():
        return
        
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return
        
    # We are looking for PLANNER_RESPONSE with tool_calls
    if data.get("type") == "PLANNER_RESPONSE" and data.get("source") == "MODEL":
        tool_calls = data.get("tool_calls", [])
        for tool_call in tool_calls:
            # Construct a synthetic PreToolUse payload for agentaudit_ingest.py
            name = tool_call.get("name", "")
            args = tool_call.get("args", {})
            
            # The ingest script expects antigravity tools without 'default_api:' prefix if we pass it directly
            # Or we can just use the hook format
            if name.startswith("default_api:"):
                name = name.split(":", 1)[1]
            
            payload = {
                "toolCall": {
                    "name": name,
                    "args": args
                },
                "conversationId": conversation_id,
                "stepIdx": data.get("step_index", 0)
            }
            
            print(f"Found tool call: {name}", flush=True)
            
            # Pipe it to the ingest script
            ingest_script = Path(__file__).parent / "agentaudit_ingest.py"
            env = os.environ.copy()
            env["AGENTAUDIT_SOURCE_APP"] = "antigravity"
            env["AGENTAUDIT_ADAPTER"] = "antigravity_transcript"
            
            try:
                process = subprocess.Popen(
                    [sys.executable, str(ingest_script), "antigravity", "hook", "PreToolUse"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env
                )
                stdout, stderr = process.communicate(input=json.dumps(payload).encode("utf-8"))
                if process.returncode != 0 or stderr:
                    err = stderr.decode("utf-8", errors="replace").strip()
                    if err:
                        print(f"Ingest stderr: {err}", flush=True)
                    if process.returncode != 0:
                        print(f"Ingest exit {process.returncode}", flush=True)
            except Exception as e:
                print(f"Failed to ingest: {e}", flush=True)

def main():
    print("Starting Antigravity Transcript Watcher...", flush=True)
    current_file = None
    tail_generator = None
    
    while True:
        latest_file = get_latest_transcript()
        
        if latest_file != current_file:
            print(f"Switched to new transcript: {latest_file}", flush=True)
            current_file = latest_file
            if current_file:
                tail_generator = tail_file(current_file)
                
        if tail_generator:
            try:
                line = next(tail_generator)
                if line:
                    conversation_id = current_file.parent.parent.parent.name
                    process_line(line, conversation_id)
            except StopIteration:
                pass
                
        time.sleep(0.5)

if __name__ == "__main__":
    main()
