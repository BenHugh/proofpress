#!/usr/bin/env python3
"""Launcher for the ProofPress MCP server. No install needed: python3 mcp/server.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from proofpress.mcp_server import main  # noqa: E402

if __name__ == "__main__":
    main()
