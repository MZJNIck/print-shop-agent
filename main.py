"""便捷入口：python main.py "..." 等价于 python -m printshop "..."。"""
import sys

from printshop.cli import main

if __name__ == "__main__":
    sys.exit(main())
