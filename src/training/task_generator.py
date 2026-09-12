"""5,000-Task Dataset Generator for NEXA Autonomous Training.

Generates realistic Windows computer-use benchmark tasks across 30 domains.
All file, archive, and execution tasks are safely contained in data/training/sandbox/.
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SRC_DIR = Path(__file__).resolve().parents[1]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


@dataclass
class TrainingTask:
    task_id: int
    category: str
    difficulty: str  # LEVEL 1 to LEVEL 5
    prompt: str
    description: str
    required_skills: list[str]
    expected_result: str
    verifier_type: str
    verifier_params: dict[str, Any]
    risk_level: str  # READ, MUTATE, CRITICAL, REMOTE
    destructive: bool = False
    requires_confirmation: bool = False
    requires_network: bool = False
    requires_external_account: bool = False


CATEGORY_QUOTAS = {
    "Application Control": 300,
    "Browser Control": 700,
    "Web Navigation": 300,
    "Search & Information": 250,
    "File Creation": 300,
    "File Reading": 200,
    "File Copy/Move": 250,
    "File Rename": 150,
    "Folder Management": 150,
    "File Organization": 200,
    "Text Editing": 200,
    "Terminal / PowerShell": 300,
    "Python Execution": 200,
    "Coding Tasks": 300,
    "Git Tasks": 150,
    "Screenshot / Screen": 100,
    "Window Management": 150,
    "Keyboard / Mouse": 150,
    "Clipboard": 100,
    "Archive / Compression": 75,
    "System Information": 100,
    "Storage Analysis": 100,
    "Network Diagnostics": 100,
    "Development Workflow": 150,
    "Multi-step Agent Tasks": 300,
    "Error Recovery Tasks": 150,
    "Self-Diagnosis Tasks": 100,
    "NEXA Self-Management": 150,
    "UI/API/WebSocket Tasks": 100,
    "Complex End-to-End Tasks": 300,
}


def generate_tasks(sandbox_dir: Path) -> list[TrainingTask]:
    tasks: list[TrainingTask] = []
    task_id = 1
    sandbox = str(sandbox_dir.resolve()).replace("\\", "/")

    # 1. Application Control (300 tasks)
    apps = [
        ("notepad", "Notepad", "notepad.exe"),
        ("calculator", "Calculator", "calc.exe"),
        ("paint", "Paint", "mspaint.exe"),
        ("chrome", "Google Chrome", "chrome.exe"),
        ("edge", "Microsoft Edge", "msedge.exe"),
        ("cmd", "Command Prompt", "cmd.exe"),
        ("powershell", "PowerShell", "powershell.exe"),
    ]
    app_verbs = ["open", "launch", "start", "run"]
    for i in range(CATEGORY_QUOTAS["Application Control"]):
        app_id, app_name, proc_name = apps[i % len(apps)]
        verb = app_verbs[(i // len(apps)) % len(app_verbs)]
        lvl = "LEVEL 1" if i % 2 == 0 else "LEVEL 2"
        prompt = f"{verb} {app_name.lower()}" if lvl == "LEVEL 1" else f"please {verb} the {app_name} application and check its state"
        tasks.append(
            TrainingTask(
                task_id=task_id,
                category="Application Control",
                difficulty=lvl,
                prompt=prompt,
                description=f"Launch and verify {app_name} on Windows",
                required_skills=["app_control"],
                expected_result=f"{app_name} process active or acknowledged",
                verifier_type="process_check",
                verifier_params={"process_name": proc_name},
                risk_level="MUTATE",
            )
        )
        task_id += 1

    # 2. Browser Control (700 tasks)
    browser_ops = [
        ("open", "open browser to http://127.0.0.1:8765", "browser_check", {"expected_url": "8765"}, "LEVEL 1"),
        ("new_tab", "open a new browser tab", "browser_check", {}, "LEVEL 1"),
        ("click", "click the submit button on the active page", "browser_check", {}, "LEVEL 2"),
        ("type", "type 'NEXA autonomous training' into search field", "browser_check", {}, "LEVEL 2"),
        ("extract", "extract text from the active page", "browser_check", {}, "LEVEL 2"),
        ("screenshot", "take a browser page screenshot", "browser_check", {}, "LEVEL 1"),
        ("tabs", "list all open browser tabs", "browser_check", {}, "LEVEL 1"),
        ("back", "navigate back in browser history", "browser_check", {}, "LEVEL 1"),
        ("refresh", "refresh the current web page", "browser_check", {}, "LEVEL 1"),
        ("switch_tab", "switch to tab 1", "browser_check", {}, "LEVEL 2"),
    ]
    for i in range(CATEGORY_QUOTAS["Browser Control"]):
        op, prompt, vtype, vparams, lvl = browser_ops[i % len(browser_ops)]
        var_prompt = f"{prompt} [variant {i+1}]"
        tasks.append(
            TrainingTask(
                task_id=task_id,
                category="Browser Control",
                difficulty=lvl,
                prompt=var_prompt,
                description=f"Browser automation: {op}",
                required_skills=["browser_control"],
                expected_result=f"Browser {op} executed cleanly",
                verifier_type=vtype,
                verifier_params=vparams,
                risk_level="MUTATE",
                requires_network=False,
            )
        )
        task_id += 1

    # 3. Web Navigation (300 tasks)
    urls = [
        "http://127.0.0.1:8765",
        "https://example.com",
        "https://en.wikipedia.org/wiki/Artificial_intelligence",
        "https://python.org",
        "https://github.com",
    ]
    for i in range(CATEGORY_QUOTAS["Web Navigation"]):
        target_url = urls[i % len(urls)]
        tasks.append(
            TrainingTask(
                task_id=task_id,
                category="Web Navigation",
                difficulty="LEVEL 2" if i % 2 == 0 else "LEVEL 3",
                prompt=f"Navigate browser to {target_url} and verify loaded page",
                description=f"Navigate to {target_url}",
                required_skills=["browser_control"],
                expected_result="Page loaded successfully",
                verifier_type="browser_check",
                verifier_params={"expected_url": target_url.split("//")[-1].split("/")[0]},
                risk_level="REMOTE",
                requires_network=True,
            )
        )
        task_id += 1

    # 4. Search & Information (250 tasks)
    topics = [
        "Python 3.14 new features",
        "Windows 11 automation techniques",
        "Machine learning algorithms",
        "Fastest web scraping libraries in Python",
        "Distributed task queues architecture",
    ]
    for i in range(CATEGORY_QUOTAS["Search & Information"]):
        topic = topics[i % len(topics)]
        tasks.append(
            TrainingTask(
                task_id=task_id,
                category="Search & Information",
                difficulty="LEVEL 2",
                prompt=f"Search for '{topic}' and summarize findings",
                description=f"Information search: {topic}",
                required_skills=["browser_control"],
                expected_result="Search results compiled",
                verifier_type="browser_check",
                verifier_params={},
                risk_level="REMOTE",
                requires_network=True,
            )
        )
        task_id += 1

    # 5. File Creation (300 tasks)
    for i in range(CATEGORY_QUOTAS["File Creation"]):
        fname = f"sandbox_file_{i+1}.txt"
        target_file = f"{sandbox}/{fname}"
        content = f"NEXA Training Content for file {i+1} generated at step {i+1}."
        tasks.append(
            TrainingTask(
                task_id=task_id,
                category="File Creation",
                difficulty="LEVEL 1" if i % 2 == 0 else "LEVEL 2",
                prompt=f"create a file at {target_file} with content '{content}'",
                description=f"Create file {fname} in sandbox",
                required_skills=["files"],
                expected_result=f"File {fname} exists with content",
                verifier_type="file_content",
                verifier_params={"path": target_file, "expected_content": content},
                risk_level="MUTATE",
            )
        )
        task_id += 1

    # 6. File Reading (200 tasks)
    for i in range(CATEGORY_QUOTAS["File Reading"]):
        fname = f"read_sample_{i+1}.txt"
        target_file = f"{sandbox}/{fname}"
        tasks.append(
            TrainingTask(
                task_id=task_id,
                category="File Reading",
                difficulty="LEVEL 1",
                prompt=f"read file at {target_file}",
                description=f"Read file {fname} and output content",
                required_skills=["files"],
                expected_result=f"File {fname} read successfully",
                verifier_type="file_exists",
                verifier_params={"path": target_file},
                risk_level="READ",
            )
        )
        task_id += 1

    # 7. File Copy/Move (250 tasks)
    for i in range(CATEGORY_QUOTAS["File Copy/Move"]):
        src_file = f"{sandbox}/src_file_{i+1}.txt"
        dst_file = f"{sandbox}/dst_file_{i+1}.txt"
        op_type = "copy" if i % 2 == 0 else "move"
        tasks.append(
            TrainingTask(
                task_id=task_id,
                category="File Copy/Move",
                difficulty="LEVEL 2",
                prompt=f"{op_type} file from {src_file} to {dst_file}",
                description=f"{op_type.title()} {src_file} to {dst_file}",
                required_skills=["files"],
                expected_result=f"File {op_type} complete",
                verifier_type="file_exists",
                verifier_params={"path": dst_file},
                risk_level="MUTATE",
            )
        )
        task_id += 1

    # 8. File Rename (150 tasks)
    for i in range(CATEGORY_QUOTAS["File Rename"]):
        old_file = f"{sandbox}/rename_old_{i+1}.txt"
        new_file = f"{sandbox}/rename_new_{i+1}.txt"
        tasks.append(
            TrainingTask(
                task_id=task_id,
                category="File Rename",
                difficulty="LEVEL 2",
                prompt=f"rename file {old_file} to {new_file}",
                description=f"Rename {old_file} to {new_file}",
                required_skills=["files"],
                expected_result=f"Renamed file exists at {new_file}",
                verifier_type="file_exists",
                verifier_params={"path": new_file},
                risk_level="MUTATE",
            )
        )
        task_id += 1

    # 9. Folder Management (150 tasks)
    for i in range(CATEGORY_QUOTAS["Folder Management"]):
        dirname = f"sandbox_dir_{i+1}"
        dir_path = f"{sandbox}/{dirname}"
        tasks.append(
            TrainingTask(
                task_id=task_id,
                category="Folder Management",
                difficulty="LEVEL 1" if i % 2 == 0 else "LEVEL 2",
                prompt=f"create directory at {dir_path}",
                description=f"Create folder {dirname}",
                required_skills=["files"],
                expected_result=f"Folder {dirname} created",
                verifier_type="folder_exists",
                verifier_params={"path": dir_path},
                risk_level="MUTATE",
            )
        )
        task_id += 1

    # 10. File Organization (200 tasks)
    for i in range(CATEGORY_QUOTAS["File Organization"]):
        target_dir = f"{sandbox}/org_dir_{i+1}"
        tasks.append(
            TrainingTask(
                task_id=task_id,
                category="File Organization",
                difficulty="LEVEL 3",
                prompt=f"organize documents in {target_dir} into structured folders",
                description="Organize unstructured files by extension",
                required_skills=["files"],
                expected_result="Files sorted into folders",
                verifier_type="folder_exists",
                verifier_params={"path": target_dir},
                risk_level="MUTATE",
            )
        )
        task_id += 1

    # 11. Text Editing (200 tasks)
    for i in range(CATEGORY_QUOTAS["Text Editing"]):
        edit_file = f"{sandbox}/edit_file_{i+1}.txt"
        appended = f"Updated line {i+1} appended."
        tasks.append(
            TrainingTask(
                task_id=task_id,
                category="Text Editing",
                difficulty="LEVEL 2",
                prompt=f"append '{appended}' to {edit_file}",
                description=f"Edit and append text to {edit_file}",
                required_skills=["files"],
                expected_result="Appended text present in file",
                verifier_type="file_content",
                verifier_params={"path": edit_file, "expected_content": appended},
                risk_level="MUTATE",
            )
        )
        task_id += 1

    # 12. Terminal / PowerShell (300 tasks)
    cmd_templates = [
        ("echo 'Hello NEXA'", "Hello NEXA"),
        ("Get-Date", "202"),
        ("Get-Location", "NEXA"),
        ("hostname", ""),
        ("dir", ""),
    ]
    for i in range(CATEGORY_QUOTAS["Terminal / PowerShell"]):
        cmd, exp = cmd_templates[i % len(cmd_templates)]
        tasks.append(
            TrainingTask(
                task_id=task_id,
                category="Terminal / PowerShell",
                difficulty="LEVEL 1" if i % 2 == 0 else "LEVEL 2",
                prompt=f"run terminal command '{cmd}'",
                description=f"Execute PowerShell command: {cmd}",
                required_skills=["terminal"],
                expected_result=f"Command executed with output {exp}",
                verifier_type="terminal_output",
                verifier_params={"expected_output": exp},
                risk_level="CRITICAL",
            )
        )
        task_id += 1

    # 13. Python Execution (200 tasks)
    py_scripts = [
        "print('Math test:', 40 + 2)",
        "import math; print('pi:', round(math.pi, 4))",
        "print('JSON test:', {'status': 'ok'})",
        "import sys; print('python version:', sys.version.split()[0])",
    ]
    for i in range(CATEGORY_QUOTAS["Python Execution"]):
        code = py_scripts[i % len(py_scripts)]
        tasks.append(
            TrainingTask(
                task_id=task_id,
                category="Python Execution",
                difficulty="LEVEL 2",
                prompt=f"execute python code \"{code}\"",
                description="Execute isolated python code snippet",
                required_skills=["terminal"],
                expected_result="Python execution verified",
                verifier_type="terminal_output",
                verifier_params={"expected_output": "test" if "test" in code else "3."},
                risk_level="CRITICAL",
            )
        )
        task_id += 1

    # 14. Coding Tasks (300 tasks)
    for i in range(CATEGORY_QUOTAS["Coding Tasks"]):
        script_path = f"{sandbox}/script_{i+1}.py"
        code_body = f"def solution_{i+1}(x):\n    return x * 2\nif __name__ == '__main__':\n    print(solution_{i+1}(21))\n"
        tasks.append(
            TrainingTask(
                task_id=task_id,
                category="Coding Tasks",
                difficulty="LEVEL 3",
                prompt=f"write python script at {script_path} implementing solution_{i+1}",
                description=f"Write python program at {script_path}",
                required_skills=["files"],
                expected_result="Python script file created",
                verifier_type="file_content",
                verifier_params={"path": script_path, "expected_content": f"def solution_{i+1}"},
                risk_level="MUTATE",
            )
        )
        task_id += 1

    # 15. Git Tasks (150 tasks)
    for i in range(CATEGORY_QUOTAS["Git Tasks"]):
        git_repo = f"{sandbox}/repo_{i+1}"
        tasks.append(
            TrainingTask(
                task_id=task_id,
                category="Git Tasks",
                difficulty="LEVEL 2",
                prompt=f"inspect git status in {git_repo}",
                description=f"Inspect git repository at {git_repo}",
                required_skills=["git"],
                expected_result="Git status evaluated",
                verifier_type="git_status",
                verifier_params={"repo_path": git_repo},
                risk_level="READ",
            )
        )
        task_id += 1

    # 16. Screenshot / Screen (100 tasks)
    for i in range(CATEGORY_QUOTAS["Screenshot / Screen"]):
        tasks.append(
            TrainingTask(
                task_id=task_id,
                category="Screenshot / Screen",
                difficulty="LEVEL 1",
                prompt="take a screenshot of the display",
                description="Capture desktop screenshot",
                required_skills=["computer"],
                expected_result="Screenshot captured",
                verifier_type="terminal_output",
                verifier_params={"expected_output": "screenshot"},
                risk_level="READ",
            )
        )
        task_id += 1

    # 17. Window Management (150 tasks)
    for i in range(CATEGORY_QUOTAS["Window Management"]):
        tasks.append(
            TrainingTask(
                task_id=task_id,
                category="Window Management",
                difficulty="LEVEL 1" if i % 2 == 0 else "LEVEL 2",
                prompt="list all open desktop windows",
                description="Enumerate active desktop windows",
                required_skills=["computer"],
                expected_result="Windows listed",
                verifier_type="terminal_output",
                verifier_params={"expected_output": "window"},
                risk_level="READ",
            )
        )
        task_id += 1

    # 18. Keyboard / Mouse (150 tasks)
    for i in range(CATEGORY_QUOTAS["Keyboard / Mouse"]):
        tasks.append(
            TrainingTask(
                task_id=task_id,
                category="Keyboard / Mouse",
                difficulty="LEVEL 2",
                prompt=f"move mouse to coordinates {100 + (i * 2)}, {200 + (i * 2)}",
                description="Move mouse with failsafe boundaries",
                required_skills=["computer"],
                expected_result="Mouse moved",
                verifier_type="terminal_output",
                verifier_params={"expected_output": "mouse"},
                risk_level="MUTATE",
            )
        )
        task_id += 1

    # 19. Clipboard (100 tasks)
    for i in range(CATEGORY_QUOTAS["Clipboard"]):
        txt = f"NEXA clipboard item {i+1}"
        tasks.append(
            TrainingTask(
                task_id=task_id,
                category="Clipboard",
                difficulty="LEVEL 2",
                prompt=f"set clipboard to '{txt}' and verify",
                description="Set and verify clipboard text",
                required_skills=["computer"],
                expected_result="Clipboard content updated",
                verifier_type="terminal_output",
                verifier_params={"expected_output": "clipboard"},
                risk_level="MUTATE",
            )
        )
        task_id += 1

    # 20. Archive / Compression (75 tasks)
    for i in range(CATEGORY_QUOTAS["Archive / Compression"]):
        zip_path = f"{sandbox}/archive_{i+1}.zip"
        target_dir = f"{sandbox}/archive_dir_{i+1}"
        tasks.append(
            TrainingTask(
                task_id=task_id,
                category="Archive / Compression",
                difficulty="LEVEL 2",
                prompt=f"create zip archive at {zip_path} from folder {target_dir}",
                description=f"Compress folder into {zip_path}",
                required_skills=["zip_create"],
                expected_result="Zip archive created",
                verifier_type="archive_contents",
                verifier_params={"archive_path": zip_path},
                risk_level="MUTATE",
            )
        )
        task_id += 1

    # 21. System Information (100 tasks)
    for i in range(CATEGORY_QUOTAS["System Information"]):
        tasks.append(
            TrainingTask(
                task_id=task_id,
                category="System Information",
                difficulty="LEVEL 1",
                prompt="report system information including CPU and OS version",
                description="Inspect system specs and OS",
                required_skills=["terminal"],
                expected_result="System metrics reported",
                verifier_type="system_info",
                verifier_params={},
                risk_level="READ",
            )
        )
        task_id += 1

    # 22. Storage Analysis (100 tasks)
    for i in range(CATEGORY_QUOTAS["Storage Analysis"]):
        tasks.append(
            TrainingTask(
                task_id=task_id,
                category="Storage Analysis",
                difficulty="LEVEL 1",
                prompt="analyze my storage on C: and D:",
                description="Perform storage audit of SSD and HDD",
                required_skills=["storage_audit"],
                expected_result="Storage report with C: and D: stats",
                verifier_type="storage_audit",
                verifier_params={},
                risk_level="READ",
            )
        )
        task_id += 1

    # 23. Network Diagnostics (100 tasks)
    for i in range(CATEGORY_QUOTAS["Network Diagnostics"]):
        tasks.append(
            TrainingTask(
                task_id=task_id,
                category="Network Diagnostics",
                difficulty="LEVEL 2",
                prompt="check network connectivity and ping 127.0.0.1",
                description="Run local network diagnostic",
                required_skills=["terminal"],
                expected_result="Ping responded successfully",
                verifier_type="terminal_output",
                verifier_params={"expected_output": "reply"},
                risk_level="READ",
            )
        )
        task_id += 1

    # 24. Development Workflow (150 tasks)
    for i in range(CATEGORY_QUOTAS["Development Workflow"]):
        wf_dir = f"{sandbox}/dev_wf_{i+1}"
        tasks.append(
            TrainingTask(
                task_id=task_id,
                category="Development Workflow",
                difficulty="LEVEL 3",
                prompt=f"setup dev project in {wf_dir} with README.md and main.py",
                description="Scaffold python project structure",
                required_skills=["files"],
                expected_result="Project scaffold created",
                verifier_type="file_exists",
                verifier_params={"path": f"{wf_dir}/README.md"},
                risk_level="MUTATE",
            )
        )
        task_id += 1

    # 25. Multi-step Agent Tasks (300 tasks)
    for i in range(CATEGORY_QUOTAS["Multi-step Agent Tasks"]):
        f1 = f"{sandbox}/ms_step_{i+1}_1.txt"
        f2 = f"{sandbox}/ms_step_{i+1}_2.txt"
        tasks.append(
            TrainingTask(
                task_id=task_id,
                category="Multi-step Agent Tasks",
                difficulty="LEVEL 3",
                prompt=f"create file {f1} containing 'step 1' then copy to {f2}",
                description="Multi-step create and copy workflow",
                required_skills=["files"],
                expected_result="Both files exist with verified content",
                verifier_type="file_exists",
                verifier_params={"path": f2},
                risk_level="MUTATE",
            )
        )
        task_id += 1

    # 26. Error Recovery Tasks (150 tasks)
    for i in range(CATEGORY_QUOTAS["Error Recovery Tasks"]):
        tasks.append(
            TrainingTask(
                task_id=task_id,
                category="Error Recovery Tasks",
                difficulty="LEVEL 4",
                prompt=f"try opening nonexistent_file_{i+1}.txt and recover safely",
                description="Graceful error recovery on missing file",
                required_skills=["files"],
                expected_result="Gracefully handled with error report",
                verifier_type="terminal_output",
                verifier_params={"expected_output": "file"},
                risk_level="READ",
            )
        )
        task_id += 1

    # 27. Self-Diagnosis Tasks (100 tasks)
    for i in range(CATEGORY_QUOTAS["Self-Diagnosis Tasks"]):
        tasks.append(
            TrainingTask(
                task_id=task_id,
                category="Self-Diagnosis Tasks",
                difficulty="LEVEL 2",
                prompt="Run capability verification",
                description="Run 17-subsystem self-diagnostic audit",
                required_skills=["self_test"],
                expected_result="All subsystems verified",
                verifier_type="self_test",
                verifier_params={},
                risk_level="READ",
            )
        )
        task_id += 1

    # 28. NEXA Self-Management (150 tasks)
    for i in range(CATEGORY_QUOTAS["NEXA Self-Management"]):
        tasks.append(
            TrainingTask(
                task_id=task_id,
                category="NEXA Self-Management",
                difficulty="LEVEL 2",
                prompt="check system status and active skills count",
                description="Inspect NEXA runtime status",
                required_skills=["workspace"],
                expected_result="System status reported",
                verifier_type="terminal_output",
                verifier_params={"expected_output": "skill"},
                risk_level="READ",
            )
        )
        task_id += 1

    # 29. UI/API/WebSocket Tasks (100 tasks)
    for i in range(CATEGORY_QUOTAS["UI/API/WebSocket Tasks"]):
        tasks.append(
            TrainingTask(
                task_id=task_id,
                category="UI/API/WebSocket Tasks",
                difficulty="LEVEL 2",
                prompt="test UI server telemetry status endpoint",
                description="Verify UI server API response",
                required_skills=["workspace"],
                expected_result="UI server status response valid",
                verifier_type="ui_response",
                verifier_params={},
                risk_level="READ",
            )
        )
        task_id += 1

    # 30. Complex End-to-End Tasks (300 tasks)
    for i in range(CATEGORY_QUOTAS["Complex End-to-End Tasks"]):
        report_file = f"{sandbox}/e2e_report_{i+1}.txt"
        tasks.append(
            TrainingTask(
                task_id=task_id,
                category="Complex End-to-End Tasks",
                difficulty="LEVEL 5",
                prompt=f"audit storage and write summary report to {report_file}",
                description="Complex cross-domain storage audit and file write",
                required_skills=["storage_audit", "files"],
                expected_result=f"Report created at {report_file}",
                verifier_type="file_exists",
                verifier_params={"path": report_file},
                risk_level="MUTATE",
            )
        )
        task_id += 1

    return tasks


def save_tasks_jsonl(tasks: list[TrainingTask], output_file: Path) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        for t in tasks:
            f.write(json.dumps(asdict(t)) + "\n")


if __name__ == "__main__":
    sandbox_path = Path("data/training/sandbox")
    sandbox_path.mkdir(parents=True, exist_ok=True)
    all_tasks = generate_tasks(sandbox_path)
    out = Path("data/training/tasks.jsonl")
    save_tasks_jsonl(all_tasks, out)
    print(f"Generated {len(all_tasks)} training tasks at {out}")
