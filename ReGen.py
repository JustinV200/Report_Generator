"""Entry point for the ReGen report generator."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from dotenv import load_dotenv
load_dotenv()

from src.core.main import main

if __name__ == "__main__":
    main()
