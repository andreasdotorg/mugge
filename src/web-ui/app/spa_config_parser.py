"""Parser for PipeWire SPA configuration format.

Extracts filter-chain internal topology (nodes, links, inputs, outputs)
from the SPA config used by 30-filter-chain-convolver.conf.
"""

from __future__ import annotations

import re
from typing import Any


def parse_spa_config(text: str) -> dict:
    """Parse PipeWire SPA config format into a Python dict.

    SPA format rules:
    - Unquoted keys (may contain dots, hyphens, underscores)
    - Values can be: quoted strings, unquoted tokens, numbers, nested { } objects, [ ] arrays
    - # starts a line comment
    - = or whitespace separates key from value
    - Entries in objects/arrays separated by newlines or commas
    """
    tokens = _tokenize(text)
    parser = _Parser(tokens)
    return parser.parse_object_body()


def extract_filter_chain_topology(config: dict) -> dict:
    """Extract the filter-chain's internal topology from parsed config.

    Returns:
        {
            "nodes": [{"type": ..., "name": ..., "label": ..., "config": {...}, "control": {...}}, ...],
            "links": [{"output_node": ..., "output_port": ..., "input_node": ..., "input_port": ...}, ...],
            "inputs": [{"node": ..., "port": ...}, ...],
            "outputs": [{"node": ..., "port": ...}, ...]
        }
    """
    # Navigate to filter.graph inside the first context.modules entry
    modules = config.get("context.modules", [])
    if not modules:
        raise ValueError("No context.modules found in config")

    module = modules[0] if isinstance(modules, list) else modules
    args = module.get("args", {})
    graph = args.get("filter.graph", {})

    nodes = []
    for node_def in graph.get("nodes", []):
        node = {
            "type": node_def.get("type"),
            "name": node_def.get("name"),
            "label": node_def.get("label"),
        }
        if "config" in node_def:
            node["config"] = node_def["config"]
        if "control" in node_def:
            node["control"] = node_def["control"]
        nodes.append(node)

    links = []
    for link_def in graph.get("links", []):
        out_str = link_def.get("output", "")
        in_str = link_def.get("input", "")
        out_node, out_port = _split_port_ref(out_str)
        in_node, in_port = _split_port_ref(in_str)
        links.append({
            "output_node": out_node,
            "output_port": out_port,
            "input_node": in_node,
            "input_port": in_port,
        })

    inputs = []
    for port_ref in graph.get("inputs", []):
        node, port = _split_port_ref(port_ref)
        inputs.append({"node": node, "port": port})

    outputs = []
    for port_ref in graph.get("outputs", []):
        node, port = _split_port_ref(port_ref)
        outputs.append({"node": node, "port": port})

    return {
        "nodes": nodes,
        "links": links,
        "inputs": inputs,
        "outputs": outputs,
    }


def _split_port_ref(ref: str) -> tuple[str, str]:
    """Split 'node_name:port_name' into (node_name, port_name)."""
    if ":" in ref:
        parts = ref.split(":", 1)
        return parts[0], parts[1]
    return ref, ""


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

# Token types
_TOK_LBRACE = "{"
_TOK_RBRACE = "}"
_TOK_LBRACKET = "["
_TOK_RBRACKET = "]"
_TOK_EQUALS = "="
_TOK_STRING = "STRING"
_TOK_EOF = "EOF"

_UNQUOTED_RE = re.compile(r'[A-Za-z0-9_.+\-/:]+')


def _tokenize(text: str) -> list[tuple[str, str]]:
    """Tokenize SPA config text into (type, value) pairs."""
    tokens: list[tuple[str, str]] = []
    i = 0
    n = len(text)

    while i < n:
        c = text[i]

        # Skip whitespace and commas (commas are separators, like whitespace)
        if c in " \t\r\n,":
            i += 1
            continue

        # Line comment
        if c == "#":
            while i < n and text[i] != "\n":
                i += 1
            continue

        # Structural tokens
        if c == "{":
            tokens.append((_TOK_LBRACE, "{"))
            i += 1
            continue
        if c == "}":
            tokens.append((_TOK_RBRACE, "}"))
            i += 1
            continue
        if c == "[":
            tokens.append((_TOK_LBRACKET, "["))
            i += 1
            continue
        if c == "]":
            tokens.append((_TOK_RBRACKET, "]"))
            i += 1
            continue
        if c == "=":
            tokens.append((_TOK_EQUALS, "="))
            i += 1
            continue

        # Quoted string
        if c == '"':
            j = i + 1
            parts = []
            while j < n and text[j] != '"':
                if text[j] == "\\" and j + 1 < n:
                    parts.append(text[j + 1])
                    j += 2
                else:
                    parts.append(text[j])
                    j += 1
            tokens.append((_TOK_STRING, "".join(parts)))
            i = j + 1
            continue

        # Unquoted token (identifier, number, path, etc.)
        m = _UNQUOTED_RE.match(text, i)
        if m:
            tokens.append((_TOK_STRING, m.group()))
            i = m.end()
            continue

        raise ValueError(f"Unexpected character {c!r} at position {i}")

    tokens.append((_TOK_EOF, ""))
    return tokens


# ---------------------------------------------------------------------------
# Recursive-descent parser
# ---------------------------------------------------------------------------

class _Parser:
    def __init__(self, tokens: list[tuple[str, str]]):
        self._tokens = tokens
        self._pos = 0

    def _peek(self) -> tuple[str, str]:
        return self._tokens[self._pos]

    def _advance(self) -> tuple[str, str]:
        tok = self._tokens[self._pos]
        self._pos += 1
        return tok

    def _expect(self, tok_type: str) -> tuple[str, str]:
        tok = self._advance()
        if tok[0] != tok_type:
            raise ValueError(f"Expected {tok_type}, got {tok[0]} ({tok[1]!r})")
        return tok

    def parse_object_body(self) -> dict[str, Any]:
        """Parse key-value pairs until } or EOF."""
        result: dict[str, Any] = {}
        while True:
            typ, val = self._peek()
            if typ in (_TOK_RBRACE, _TOK_EOF):
                break
            if typ != _TOK_STRING:
                raise ValueError(f"Expected key, got {typ} ({val!r})")
            key = self._advance()[1]

            # Optional = between key and value
            if self._peek()[0] == _TOK_EQUALS:
                self._advance()

            result[key] = self._parse_value()
        return result

    def _parse_value(self) -> Any:
        typ, val = self._peek()

        if typ == _TOK_LBRACE:
            self._advance()
            obj = self.parse_object_body()
            self._expect(_TOK_RBRACE)
            return obj

        if typ == _TOK_LBRACKET:
            return self._parse_array()

        if typ == _TOK_STRING:
            self._advance()
            return _coerce_value(val)

        raise ValueError(f"Expected value, got {typ} ({val!r})")

    def _parse_array(self) -> list[Any]:
        self._expect(_TOK_LBRACKET)
        items: list[Any] = []
        while True:
            typ, _ = self._peek()
            if typ == _TOK_RBRACKET:
                self._advance()
                break
            items.append(self._parse_value())
        return items


def _coerce_value(s: str) -> int | float | bool | str:
    """Convert a string token to its natural Python type."""
    if s == "true":
        return True
    if s == "false":
        return False
    # Try int
    try:
        return int(s)
    except ValueError:
        pass
    # Try float
    try:
        return float(s)
    except ValueError:
        pass
    return s
