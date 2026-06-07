from dotenv import load_dotenv

# Why: loading .env at import keeps local CLI, tests, and app startup consistent.
load_dotenv()
