import io, json
from rich.console import Console

def emit(s):
    buf = io.StringIO()
    c = Console(file=buf, width=400, force_terminal=False, no_color=True)
    try:
        c.print(s)
        return "OK -> " + repr(buf.getvalue())
    except Exception as e:
        return f"RAISED {type(e).__name__}: {e}"

payload = json.dumps({"title": "quiz [review] draft", "note": "x[/]y", "ok": True})
print("console.print(json):", emit(payload))
print("console.print_json :", end=" ")
buf = io.StringIO()
c = Console(file=buf, width=400, force_terminal=False, no_color=True)
try:
    c.print_json(payload)
    print("OK ->", repr(buf.getvalue()))
except Exception as e:
    print(f"RAISED {type(e).__name__}: {e}")
