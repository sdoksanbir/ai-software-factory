## AI Software Factory

This repository contains the source code for the AI Software Factory project. The project aims to create a system where AI can generate and execute tasks in a controlled and secure manner. Below are the instructions to set up and run the project.

### Prerequisites

- Python 3.10 or higher
- Node.js and npm
- Git
- Ollama (AI model server)

### Setup

1. **Clone the Repository**

   ```bash
   git clone https://github.com/sdoksanbir/ai-software-factory.git
   cd ai-software-factory
   ```

2. **Install Backend Dependencies**

   ```bash
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

3. **Install Frontend Dependencies**

   ```bash
   cd frontend
   npm install
   cd ..
   ```

4. **Start Ollama Server**

   ```bash
   ollama start
   ```

5. **Run Backend**

   ```bash
   .\.venv\Scripts\Activate.ps1
   python -m uvicorn api.app:app --host 127.0.0.1 --port 8000
   ```

6. **Run Frontend**

   ```bash
   cd frontend
   npm run dev
   ```

### Testing

To run specific tests, use the following commands:

```bash
python -m pytest tests/test_task_step_handlers.py -q
```

For multi-step infrastructure tests:

```bash
python -m pytest \
    tests/test_task_execution_dispatcher.py \
    tests/test_multi_step_task_runner.py \
    tests/test_task_step_executor.py \
    tests/test_task_step_handlers.py \
    -q
```

### Git Worktree

To check active AI tasks' worktrees:

```bash
 git worktree list
```

### Git Status

Before starting work and committing:

```bash
 git status
```

### GitHub Push

To push changes to GitHub:

```bash
 git add .
 git commit -m "Descriptive commit message"
 git push
```

### Security

AI does not directly modify the `master` branch.

### Task States

Tasks can have various states such as `queued`, `running`, `failed`, `ready_for_approval`, `approved`, and `rejected`.

### Human Approval

Successful WRITE tasks are not automatically merged into the `master` branch.

### Dynamic Task Plan UI

The frontend dynamically retrieves the task plan from the backend.

### Checkpoints

At FAZ 17, the system has the following features:

- Multi-step planning
- Multi-step execution
- Persistent task plans
- Per-step retry
- Resume
- Scoped verification
- Requirement guard
- Human approval
- Dynamic plan UI

### Long-term Goal

The goal is to create a system where different AI agents can take over tasks.

### Development Principles

- AI should not work directly on the `master` branch.
- Each WRITE task should use an isolated worktree.
- Model output should be verified before application.
- File scope should be limited as much as possible.
- Tests should not introduce new behaviors based on user requirements.
- Completed multi-step steps should not be retried.
- Task state and plan information should be persistent.
- Human approval should be required before merging.
- Local models should be used as much as possible.
- Provider dependencies should be minimized.

### Quick Start

For daily use:

**Backend:**

```bash
 cd C:\Users\sdoks\Documents\ai-software-factory
 .\.venv\Scripts\Activate.ps1
 python -m uvicorn api.app:app --host 127.0.0.1 --port 8000
```

**Frontend:**

```bash
 cd C:\Users\sdoks\Documents\ai-software-factory\frontend
 npm run dev
```

**Ollama Control:**

```bash
 ollama list
```

### Repository

```text
https://github.com/sdoksanbir/ai-software-factory
```

### Status

The project is currently in active development.

Current stable base:

```text
FAZ 17
