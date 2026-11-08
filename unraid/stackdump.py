import sys, time
out = []
for tid, fr in sys._current_frames().items():
    f = fr; chain = []; sockinfo = ""
    while f is not None:
        name = f.f_code.co_name
        chain.append(f.f_code.co_filename.split("/")[-1] + ":" + name)
        if name in ("_getresponse", "getresponse") and not sockinfo:
            s = f.f_locals.get("self"); sk = getattr(s, "sock", None)
            try:
                sockinfo = "sock=%s host=%s" % (sk.getsockname()[1], getattr(s, "host", ""))
            except Exception:
                sockinfo = "sock=?"
        if name == "get_node_data":
            chain.append("[%s]" % str(f.f_locals.get("drivewsid", ""))[:70])
        f = f.f_back
    if any("ssl.py" in c or "socket.py" in c for c in chain):
        keep = [c for c in chain if not c.startswith(("threading", "<"))]
        out.append(time.strftime("%H:%M:%S") + " tid=%s %s :: " % (tid, sockinfo) + " < ".join(keep[:30]))
with open("/tmp/stack2.txt", "a") as fh:
    fh.write(("\n".join(out) + "\n") if out else time.strftime("%H:%M:%S") + " nessuna attesa di rete\n")
