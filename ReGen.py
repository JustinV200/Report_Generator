"""Entry point for the ReGen report generator."""

from dotenv import load_dotenv
load_dotenv()

from core.pipeline import main

if __name__ == "__main__":
    main()
