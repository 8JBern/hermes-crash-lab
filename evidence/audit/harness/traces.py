import json, re, glob, collections, sys
for f in sorted(glob.glob("*.jsonl")):
    ok = bad = 0
    for l in open(f):
        try: json.loads(l); ok += 1
        except Exception: bad += 1
    t = open(f).read()
    print("==", f, "json-lines ok", ok, "bad", bad, "| tool mentions", dict(collections.Counter(re.findall(r"crash_[a-z]+", t))))
    print("   sensitive:", {k: len(re.findall(k, t)) for k in ["/home/barry", "sk-[A-Za-z0-9]{8,}", "api_key", "Bearer ", "@gmail", "retry_count"]})
