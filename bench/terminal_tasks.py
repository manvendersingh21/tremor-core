"""15 tasks for the terminal agent. Each: starting files, request, files to add, hidden grader test, optional check.

Graded by running the hidden `_grade_test.py` (pytest) after the agent has edited the repo.
"""
from __future__ import annotations

import ast
import pathlib

T: list[dict] = []


def task(id, name, files, request, add, grade, check=None, test_first=False, hard=False):
    T.append(dict(id=id, name=name, files=files, request=request, add=add, grade=grade, check=check,
                  test_first=test_first, hard=hard))


def _defs(d: pathlib.Path, f: str):
    return [n for n in ast.walk(ast.parse((d / f).read_text())) if isinstance(n, ast.FunctionDef)]


task(1, "fizzbuzz + tests", {"README.md": "# demo\n"},
     "Create fizz.py with fizzbuzz(n) returning a list of n strings for 1..n: 'Fizz' for multiples of 3, 'Buzz' for 5, "
     "'FizzBuzz' for both, else the number as a string. Also create test_fizz.py with pytest tests.", [],
     "from fizz import fizzbuzz\ndef test_g():\n    r = fizzbuzz(15)\n    assert r[2] == 'Fizz' and r[4] == 'Buzz' and r[14] == 'FizzBuzz' and r[0] == '1' and len(r) == 15\n    assert fizzbuzz(0) == []\n",
     check=lambda d: (d / "test_fizz.py").exists())

task(2, "off-by-one", {"rangeutil.py": "def last_n(items, n):\n    \"\"\"Return the last n items.\"\"\"\n    return items[len(items) - n + 1:]\n",
                       "test_rangeutil.py": "from rangeutil import last_n\ndef test_last():\n    assert last_n([1, 2, 3, 4], 2) == [3, 4]\n"},
     "Fix the off-by-one bug in last_n.", ["rangeutil.py"],
     "from rangeutil import last_n\ndef test_g():\n    assert last_n([1,2,3,4],2)==[3,4] and last_n([1,2,3],3)==[1,2,3] and last_n([1,2,3],1)==[3]\n", test_first=True)

task(3, "add CLI flag", {"hello.py": "import argparse\n\ndef main(argv=None):\n    p = argparse.ArgumentParser()\n    p.add_argument('--name', default='world')\n    a = p.parse_args(argv)\n    return f'hello, {a.name}'\n"},
     "Add a --shout flag to main in hello.py. When given, the returned greeting is upper case.", ["hello.py"],
     "from hello import main\ndef test_g():\n    assert main(['--name','bob','--shout']) == 'HELLO, BOB' and main(['--name','bob']) == 'hello, bob'\n")

task(4, "regex validator", {"validators.py": "import re\n"},
     "In validators.py add is_hex_color(s) returning True for strings like '#fff' or '#A1b2C3' (# plus 3 or 6 hex digits) and False otherwise.", ["validators.py"],
     "from validators import is_hex_color as f\ndef test_g():\n    assert f('#fff') and f('#A1b2C3') and not f('fff') and not f('#ffff') and not f('#ggg') and not f('#fff\\n')\n")

task(5, "SQL helper", {"db.py": "import sqlite3\n"},
     "In db.py add top_customers(conn, n) that runs a SQL query on table orders(customer TEXT, amount REAL) and returns a list of (customer, total) tuples for the n customers with the largest total amount, biggest first.", ["db.py"],
     "import sqlite3\nfrom db import top_customers\ndef test_g():\n    c = sqlite3.connect(':memory:')\n    c.execute('create table orders(customer text, amount real)')\n    c.executemany('insert into orders values(?,?)', [('a',5),('b',20),('a',30),('c',1)])\n    assert top_customers(c, 2) == [('a',35.0),('b',20.0)]\n")

task(6, "refactor", {"calc.py": "def area_square(s):\n    if s < 0:\n        raise ValueError('negative')\n    return s * s\n\ndef area_circle(r):\n    if r < 0:\n        raise ValueError('negative')\n    return 3.14159 * r * r\n\ndef area_rect(w, h):\n    if w < 0 or h < 0:\n        raise ValueError('negative')\n    return w * h\n",
                     "test_calc.py": "import pytest\nfrom calc import *\ndef test_a():\n    assert area_square(2) == 4 and area_rect(2, 3) == 6 and abs(area_circle(1) - 3.14159) < 1e-9\n    with pytest.raises(ValueError):\n        area_rect(-1, 2)\n"},
     "Refactor calc.py: move the repeated negative check into one helper function and call it from the three area functions. Behaviour must not change.", ["calc.py"],
     "import pytest\nfrom calc import *\ndef test_g():\n    assert area_square(3) == 9 and area_rect(2, 5) == 10\n    for f, a in ((area_square, (-1,)), (area_circle, (-1,)), (area_rect, (1, -1))):\n        with pytest.raises(ValueError):\n            f(*a)\n",
     check=lambda d: len(_defs(d, "calc.py")) >= 4)

task(7, "type hints", {"textutil.py": "def shout(s):\n    return s.upper() + '!'\n\ndef repeat(s, n):\n    return s * n\n\ndef first_word(s):\n    return s.split()[0] if s.split() else ''\n"},
     "Add type hints to every function in textutil.py (all arguments and return types).", ["textutil.py"],
     "from textutil import *\ndef test_g():\n    assert shout('a') == 'A!' and repeat('a', 2) == 'aa' and first_word('x y') == 'x'\n",
     check=lambda d: all(f.returns is not None and all(a.annotation for a in f.args.args) for f in _defs(d, "textutil.py")))

task(8, "docstrings", {"mathx.py": "def add(a, b):\n    return a + b\n\ndef mean(xs):\n    return sum(xs) / len(xs)\n\ndef clamp(x, lo, hi):\n    return max(lo, min(x, hi))\n"},
     "Add a one-line docstring to every function in mathx.py. Do not change the code.", ["mathx.py"],
     "from mathx import *\ndef test_g():\n    assert add(1, 2) == 3 and mean([1, 3]) == 2 and clamp(5, 0, 3) == 3\n",
     check=lambda d: all(ast.get_docstring(f) for f in _defs(d, "mathx.py")))

task(9, "fix failing test", {"stack.py": "class Stack:\n    def __init__(self):\n        self.items = []\n\n    def push(self, x):\n        self.items.append(x)\n\n    def pop(self):\n        return self.items.pop(0)\n",
                             "test_stack.py": "from stack import Stack\ndef test_lifo():\n    s = Stack(); s.push(1); s.push(2)\n    assert s.pop() == 2 and s.pop() == 1\n"},
     "The test in test_stack.py fails. Fix stack.py, not the test.", ["stack.py", "test_stack.py"],
     "from stack import Stack\ndef test_g():\n    s = Stack(); [s.push(i) for i in (1, 2, 3)]\n    assert [s.pop(), s.pop(), s.pop()] == [3, 2, 1]\n", test_first=True)

task(10, "word counts", {"words.py": "def top_words(text, n):\n    pass\n"},
     "Implement top_words(text, n) in words.py: lower-case the text, split on whitespace, and return the n most common words as (word, count) tuples, most common first, ties in alphabetical order.", ["words.py"],
     "from words import top_words\ndef test_g():\n    assert top_words('b a B c a', 2) == [('a', 2), ('b', 2)] and top_words('', 3) == []\n")

task(11, "rename across 2 files", {"lib.py": "def calc_total(items):\n    return sum(items)\n",
                                   "app.py": "from lib import calc_total\n\ndef report(items):\n    return f'total={calc_total(items)}'\n"},
     "Rename calc_total to compute_total in lib.py and update app.py to use it.", ["lib.py", "app.py"],
     "from app import report\nimport lib\ndef test_g():\n    assert report([1, 2]) == 'total=3' and lib.compute_total([4]) == 4 and not hasattr(lib, 'calc_total')\n")

task(12, "config loader", {"config.py": "import json\n"},
     "In config.py add load(path, defaults) that reads a JSON object from path and returns a dict of defaults updated with the file's keys. If the file does not exist return a copy of defaults.", ["config.py"],
     "import json\nfrom config import load\ndef test_g(tmp_path):\n    p = tmp_path / 'c.json'; p.write_text(json.dumps({'b': 2}))\n    d = {'a': 1, 'b': 0}\n    assert load(str(p), d) == {'a': 1, 'b': 2} and d == {'a': 1, 'b': 0}\n    assert load(str(tmp_path / 'no.json'), d) == d and load(str(tmp_path / 'no.json'), d) is not d\n")

task(13, "HARD: todo done command (2 files)",
     {"store.py": "import json, pathlib\n\nclass Store:\n    def __init__(self, path):\n        self.path = pathlib.Path(path)\n\n    def _load(self):\n        return json.loads(self.path.read_text()) if self.path.exists() else []\n\n    def add(self, text):\n        items = self._load()\n        items.append({'id': len(items) + 1, 'text': text, 'done': False})\n        self.path.write_text(json.dumps(items))\n\n    def list(self):\n        return self._load()\n",
      "todo.py": "import sys\nfrom store import Store\n\ndef main(argv, path='todo.json'):\n    s = Store(path)\n    if argv[0] == 'add':\n        s.add(' '.join(argv[1:]))\n        return 'added'\n    if argv[0] == 'list':\n        return '\\n'.join(f\"{i['id']} {i['text']}\" for i in s.list())\n    return 'unknown'\n"},
     "Add a 'done' feature across store.py and todo.py: Store.done(id) marks the item done and raises KeyError if the id does not exist; the CLI command 'done <id>' calls it and returns 'done'; 'list' shows '[x]' before done items text (format: '1 [x] text' for done, '1 text' for open).", ["store.py", "todo.py"],
     "import pytest\nfrom store import Store\nfrom todo import main\ndef test_g(tmp_path):\n    p = str(tmp_path / 't.json')\n    main(['add', 'a b'], p); main(['add', 'c'], p)\n    assert main(['done', '1'], p) == 'done'\n    assert main(['list'], p) == '1 [x] a b\\n2 c'\n    with pytest.raises(KeyError):\n        Store(p).done(9)\n", hard=True)

task(14, "HARD: LRU cache class", {"lru.py": ""},
     "Write class LRU in lru.py. LRU(capacity) with get(key) returning the value or None, put(key, value) storing it and evicting the least recently used key when over capacity (both get and put count as use), and __len__.", ["lru.py"],
     "from lru import LRU\ndef test_g():\n    c = LRU(2); c.put('a', 1); c.put('b', 2); assert c.get('a') == 1\n    c.put('c', 3)\n    assert c.get('b') is None and c.get('a') == 1 and c.get('c') == 3 and len(c) == 2\n    c.put('a', 9); c.put('d', 4)\n    assert c.get('c') is None and c.get('a') == 9\n", hard=True)

task(15, "HARD: report --format (2 files)",
     {"report.py": "def rows():\n    return [('apple', 3), ('pear', 5)]\n\ndef render(fmt='text'):\n    if fmt == 'text':\n        return '\\n'.join(f'{n}: {c}' for n, c in rows())\n    raise ValueError(fmt)\n",
      "rcli.py": "import sys\nfrom report import render\n\ndef main(argv):\n    return render('text')\n"},
     "Extend the report: render(fmt) in report.py must also support 'csv' (header 'name,count' then one 'name,count' line per row) and 'json' (a JSON list of objects with keys name and count). In rcli.py make main read an optional --format csv|json|text argument from argv (default text) and pass it to render.", ["report.py", "rcli.py"],
     "import json\nimport pytest\nfrom report import render\nfrom rcli import main\ndef test_g():\n    assert render('csv') == 'name,count\\napple,3\\npear,5'\n    assert json.loads(render('json')) == [{'name': 'apple', 'count': 3}, {'name': 'pear', 'count': 5}]\n    assert main(['--format', 'csv']) == render('csv') and main([]) == render('text')\n    with pytest.raises(ValueError):\n        render('xml')\n", hard=True)
