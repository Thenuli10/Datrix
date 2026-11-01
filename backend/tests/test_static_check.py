import pytest

from app.sandbox.static_check import MAX_CODE_BYTES, check_code

GOOD = '''
import json, os
from pathlib import Path
import numpy as np
import pandas as pd

def run(input_dir, output_dir, params):
    df = pd.read_parquet(os.path.join(input_dir, "sales.parquet"))
    total = float(df["amount"].sum())
    with open(os.path.join(output_dir, "results.json"), "w") as f:
        json.dump({"summary": {"title": "t", "rows_processed": len(df)}, "kpis": [
            {"key": "total", "label": "Total", "value": total}]}, f)
    open("/output/extra.txt", "w").write("ok")
    Path(output_dir, "x.csv").write_text("a")
    os.makedirs(os.path.join(output_dir, "artifacts"), exist_ok=True)
'''


def test_allows_normal_pandas_code():
    assert check_code(GOOD) == []


@pytest.mark.parametrize("snippet", [
    "import subprocess",
    "import socket",
    "import requests",
    "import urllib.request",
    "from http import client",
    "import ftplib",
    "import smtplib",
    "import ctypes",
    "from multiprocessing import Pool",
    "import shutil\nshutil.rmtree('/output')",
    "from shutil import rmtree",
    "import os\nos.system('ls')",
    "import os\nos.popen('ls')",
    "import os\nos.execv('/bin/sh', [])",
    "import os\nos.fork()",
    "import os\nos.spawnl(0, 'x')",
    "from os import system",
    "eval('1+1')",
    "exec('x=1')",
    "compile('1', 'f', 'eval')",
    "__import__('os')",
    "open('/etc/passwd')",
    "open('../secret.txt')",
    "x = ().__class__.__bases__[0].__subclasses__()",
])
def test_rejects_banned_pattern(snippet):
    assert check_code(snippet), snippet


def test_size_limit_and_syntax_error():
    assert check_code("x = 1\n" * (MAX_CODE_BYTES // 6 + 10))
    assert "syntax error" in check_code("def f(:\n")[0]
