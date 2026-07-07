"""Minimal S-expression reader/writer for KiCad files (stdlib only).

Atoms are str (bare or quoted), int, or float. Lists are Python lists whose
first element is conventionally the node name. Quoted strings are represented
as Quoted instances so bare tokens and strings round-trip distinctly.
"""


class Quoted(str):
    """A string that must be emitted with double quotes."""
    __slots__ = ()


def parse(text):
    """Parse one or more top-level S-expressions; returns a list of nodes."""
    tokens = _tokenize(text)
    pos = 0
    nodes = []
    while pos < len(tokens):
        node, pos = _parse_node(tokens, pos)
        nodes.append(node)
    return nodes


def parse_one(text):
    nodes = parse(text)
    if len(nodes) != 1:
        raise ValueError(f"expected exactly one top-level node, got {len(nodes)}")
    return nodes[0]


def _tokenize(text):
    tokens = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
        elif c == "(" or c == ")":
            tokens.append(c)
            i += 1
        elif c == '"':
            j = i + 1
            buf = []
            while j < n:
                if text[j] == "\\" and j + 1 < n:
                    buf.append(text[j:j + 2])
                    j += 2
                elif text[j] == '"':
                    break
                else:
                    buf.append(text[j])
                    j += 1
            if j >= n:
                raise ValueError("unterminated string")
            tokens.append(('"', "".join(buf)))
            i = j + 1
        else:
            j = i
            while j < n and text[j] not in ' \t\r\n()"':
                j += 1
            tokens.append(("a", text[i:j]))
            i = j
    return tokens


def _parse_node(tokens, pos):
    tok = tokens[pos]
    if tok == "(":
        pos += 1
        items = []
        while tokens[pos] != ")":
            item, pos = _parse_node(tokens, pos)
            items.append(item)
        return items, pos + 1
    if tok == ")":
        raise ValueError("unexpected )")
    kind, value = tok
    if kind == '"':
        return Quoted(_unescape(value)), pos + 1
    return _atom(value), pos + 1


def _unescape(s):
    return s.replace('\\"', '"').replace("\\\\", "\\").replace("\\n", "\n")


def _atom(tok):
    try:
        return int(tok)
    except ValueError:
        pass
    try:
        return float(tok)
    except ValueError:
        pass
    return tok


def _escape(s):
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _fmt_atom(a):
    if isinstance(a, Quoted):
        return f'"{_escape(a)}"'
    if isinstance(a, bool):
        return "yes" if a else "no"
    if isinstance(a, float):
        # KiCad writes shortest decimal form; avoid trailing zeros / sci notation
        s = f"{a:.6f}".rstrip("0").rstrip(".")
        return s if s not in ("", "-") else "0"
    return str(a)


def dump(node, indent=0):
    """Serialize a node with stable, deterministic formatting."""
    if not isinstance(node, list):
        return _fmt_atom(node)
    pad = "  " * indent
    # Short leaf lists stay on one line
    if all(not isinstance(x, list) for x in node):
        return pad + "(" + " ".join(_fmt_atom(x) for x in node) + ")" if indent == 0 else \
            "(" + " ".join(_fmt_atom(x) for x in node) + ")"
    parts = []
    head = []
    i = 0
    while i < len(node) and not isinstance(node[i], list):
        head.append(_fmt_atom(node[i]))
        i += 1
    parts.append("(" + " ".join(head))
    for child in node[i:]:
        if isinstance(child, list):
            parts.append("  " * (indent + 1) + dump(child, indent + 1))
        else:
            parts.append("  " * (indent + 1) + _fmt_atom(child))
    parts.append("  " * indent + ")")
    return "\n".join(parts)


def dumps(node):
    return dump(node, 0) + "\n"


# --- convenience accessors -------------------------------------------------

def children(node, name):
    """All child lists whose head atom equals name."""
    return [c for c in node if isinstance(c, list) and c and c[0] == name]


def child(node, name):
    cs = children(node, name)
    return cs[0] if cs else None


def atom_after(node, name, default=None):
    """Value following the head in a child list: (name value)."""
    c = child(node, name)
    return c[1] if c and len(c) > 1 else default
