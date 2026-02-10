   #!/bin/bash
   cd "$(dirname "$0")"
   source .venv/bin/activate
   uvicorn app_main:app --host 127.0.0.1 --port 8000