import json

log_path = "/Users/ahmev/.gemini/antigravity/brain/7d22781a-a299-4303-8338-e971e957cbe4/.system_generated/logs/transcript.jsonl"

found_entries = []
with open(log_path, 'r', encoding='utf-8') as f:
    for line in f:
        try:
            data = json.loads(line)
            content_str = json.dumps(data)
            if "django.po" in content_str:
                found_entries.append(data)
        except Exception as e:
            pass

print(f"Found {len(found_entries)} entries.")
for idx, entry in enumerate(found_entries):
    print(f"--- Entry {idx} ---")
    print("Type:", entry.get("type"))
    print("Status:", entry.get("status"))
    
    # Try to find the file path from tool_calls
    tool_calls = entry.get("tool_calls", [])
    for tc in tool_calls:
        args = tc.get("args", {})
        path = args.get("AbsolutePath") or args.get("TargetFile") or args.get("SearchPath")
        if path:
            print("File Path:", path)
    
    # Check content or response length
    content = entry.get("content", "")
    if content:
        print("Content length:", len(content))
        # If it looks like it contains the po content, let's dump it
        if "msgid" in content and "msgstr" in content:
            with open(f"/Users/ahmev/Code/Al-Maghrib/scratch/recovered_po_{idx}.txt", "w", encoding="utf-8") as out:
                out.write(content)
                print(f"Saved to recovered_po_{idx}.txt")
