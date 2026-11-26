with open('.env') as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith('#'): continue
        if '=' in line:
            k, v = line.split('=', 1)
            v = v.strip().strip('"\'')
            if 'KEY' in k or 'SECRET' in k or 'TOKEN' in k:
                print(f"{k}: set={bool(v)}, len={len(v)}, prefix={v[:7] if len(v)>=7 else v[:2]}")
