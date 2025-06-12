from pathlib import Path
import os
from dotenv import load_dotenv
import openai            # <-- added

print("🔍  Working dir:", Path().resolve())

loaded = load_dotenv()
print("📄  load_dotenv() returned:", loaded)
print("🔑  OPENAI_API_KEY present? ", bool(os.getenv("OPENAI_API_KEY")))

# ---------- NEW SECTION ----------
openai.api_key = os.getenv("OPENAI_API_KEY")

try:
    openai.models.list()           # cheapest possible request
    print("✅  OpenAI API reachable and key is valid")
except Exception as e:
    print("❌  OpenAI error →", e)
# ---------------------------------
