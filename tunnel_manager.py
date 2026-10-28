import subprocess
import os
import re
import sys
import time

# Garante suporte a UTF-8 em terminais Windows (cp1252)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

PORT = int(os.environ.get("PORT", 8000))
CANDIDATE_PATHS = [
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "bin", "cloudflared.exe")),
    os.path.abspath(os.path.join(os.path.dirname(__file__), "bin", "cloudflared.exe")),
    "cloudflared"
]

def find_cloudflared():
    for p in CANDIDATE_PATHS:
        if os.path.exists(p):
            return p
    return "cloudflared"

def start_tunnel():
    binary = find_cloudflared()
    print(f"🚀 [Cloudflare 24/7] Iniciando Quick Tunnel seguro para porta {PORT}...")
    print(f"📌 Executável: {binary} (flag: --no-prechecks)")
    
    cmd = [binary, "tunnel", "--no-prechecks", "--url", f"http://localhost:{PORT}"]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    except Exception as e:
        print(f"❌ Erro ao iniciar cloudflared: {e}")
        return

    url_found = False
    for line in iter(proc.stdout.readline, ''):
        print(line, end="")
        match = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", line)
        if match and not url_found:
            url_found = True
            public_url = match.group(0)
            print("\n" + "="*70)
            print(f"🌐 [ONLINE 24/7] TÚNEL PÚBLICO CLOUDFLARE ATIVO!")
            print(f"🔗 URL: {public_url}")
            print(f"📱 Webhook WhatsApp: {public_url}/webhook/whatsapp")
            print(f"🩺 Health Check: {public_url}/api/health")
            print("="*70 + "\n")
            
            with open("public_tunnel_url.txt", "w", encoding="utf-8") as f:
                f.write(public_url)
            break

    proc.wait()

if __name__ == "__main__":
    start_tunnel()

