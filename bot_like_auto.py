import os, json, re, webbrowser, sys, time, requests
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime, timezone

# =========================
# CONFIG
# =========================
BASE = Path(__file__).resolve().parent
env = BASE/".env"; load_dotenv(env, override=True)

STATE = BASE/"state.json"; STATE.touch(exist_ok=True)
SEED  = BASE/"seed_ids.txt"; SEED.touch(exist_ok=True)
OAUTH2_TOKEN = BASE/"oauth2_token.json"

CLIENT_ID    = os.getenv("CLIENT_ID","").strip()
REDIRECT_URI = os.getenv("REDIRECT_URI","http://127.0.0.1:8080/callback").strip()
AUTH_FLOW    = os.getenv("AUTH_FLOW","local").strip().lower()  # "local" o "paste"
ACTION       = os.getenv("ACTION","auto").strip().lower()      # "like" | "bookmark" | "auto"

# Permitir HTTP local para oauthlib (solo dev)
if REDIRECT_URI.startswith("http://127.0.0.1"):
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

SCOPES = ["tweet.read","users.read","like.write","offline.access","bookmark.read","bookmark.write"]
BASE_URL = "https://api.twitter.com/2"

def now(): return int(datetime.now(timezone.utc).timestamp())

def load_state():
    try: s=json.loads(STATE.read_text("utf-8") or "{}")
    except: s={}
    s.setdefault("queue", [])
    s.setdefault("last_search_ts", 0)
    s.setdefault("search_block_until", 0)
    s.setdefault("since_id", None)
    s.setdefault("last_like_ts", 0)      # se usa también para bookmark spacing
    return s

def save_state(s): STATE.write_text(json.dumps(s, indent=2), encoding="utf-8")

def parse_seed_ids():
    txt = SEED.read_text("utf-8", errors="ignore")
    ids=[]
    for line in txt.splitlines():
        line=line.strip()
        if not line: continue
        m=re.search(r"/status/(\d+)", line)
        if m: ids.append(m.group(1)); continue
        m=re.match(r"^\d{12,25}$", line)
        if m: ids.append(m.group(0)); continue
        m=re.search(r"(\d{12,25})", line)
        if m: ids.append(m.group(1))
    return ids

def add_from_seed(state):
    existing=set(state["queue"]); new=[]
    for tid in parse_seed_ids():
        if tid not in existing: new.append(tid)
    if new:
        state["queue"].extend(new)
        print(f"🧩 Semilla: +{len(new)} IDs (cola={len(state['queue'])})")

def seconds_until_reset(resp):
    try:
        reset=int(resp.headers.get("x-rate-limit-reset","0"))
        return max(0, reset-now())
    except: return 15*60

# =========================
# OAuth2 (PKCE) para obtener access_token de usuario
# =========================
def get_access_token():
    if not CLIENT_ID:
        raise RuntimeError("Falta CLIENT_ID en .env (OAuth 2.0 Client ID).")

    token=None
    if OAUTH2_TOKEN.exists():
        try: token=json.loads(OAUTH2_TOKEN.read_text("utf-8"))
        except: token=None

    import tweepy
    handler = tweepy.OAuth2UserHandler(
        client_id=CLIENT_ID,
        redirect_uri=REDIRECT_URI,
        scope=SCOPES,
    )

    def alt_url(url):
        return url.replace("https://twitter.com/i/oauth2/authorize","https://x.com/i/oauth2/authorize")

    if not token:
        auth_url = handler.get_authorization_url()
        print("🔑 Autoriza en uno de estos enlaces:")
        print("  1) ", auth_url)
        print("  2) ", alt_url(auth_url), " (alternativa)")

        if AUTH_FLOW == "local":
            class CallbackHandler(BaseHTTPRequestHandler):
                query_string = None
                def do_GET(self):
                    CallbackHandler.query_string = urlparse(self.path).query
                    self.send_response(200)
                    self.send_header("Content-Type","text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(b"<h3>Autorizado. Puedes cerrar esta ventana.</h3>")
                def log_message(self, *args, **kwargs): return

            try: webbrowser.open(alt_url(auth_url)) or webbrowser.open(auth_url)
            except: pass

            host = "127.0.0.1"; port = int(urlparse(REDIRECT_URI).port or 8080)
            from http.server import HTTPServer
            HTTPServer((host, port), CallbackHandler).handle_request()
            if not CallbackHandler.query_string:
                raise RuntimeError("No se recibio el callback con 'code'. Revise Redirect URI/puerto.")
            redirect_response = f"{REDIRECT_URI}?{CallbackHandler.query_string}"
        else:
            print("\n📝 Autoriza y pega aquí la URL FINAL de redirección con '?code='")
            redirect_response = input("URL de redirección: ").strip()
            if "code=" not in redirect_response:
                raise RuntimeError("La URL pegada no contiene 'code='.")

        token = handler.fetch_token(redirect_response)
        OAUTH2_TOKEN.write_text(json.dumps(token, indent=2), encoding="utf-8")
        print("💾 Token OAuth2 guardado.")

    # Refresh si hace falta
    if token.get("expires_at") and now() > int(token["expires_at"]) - 60 and "refresh_token" in token:
        token = handler.refresh_token(
            token_url="https://api.twitter.com/2/oauth2/token",
            refresh_token=token["refresh_token"]
        )
        OAUTH2_TOKEN.write_text(json.dumps(token, indent=2), encoding="utf-8")
        print("🔄 Token refrescado.")

    return token["access_token"]

# =========================
# Llamadas HTTP v2 con requests
# =========================
def api_get(path, access_token, params=None):
    url = f"{BASE_URL}{path}"
    r = requests.get(url, headers={"Authorization": f"Bearer {access_token}"}, params=params, timeout=20)
    if r.status_code >= 400:
        raise requests.HTTPError(f"{r.status_code} {r.text}", response=r)
    return r.json(), r

def api_post(path, access_token, payload):
    url = f"{BASE_URL}{path}"
    r = requests.post(url, headers={
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }, json=payload, timeout=20)
    if r.status_code >= 400:
        raise requests.HTTPError(f"{r.status_code} {r.text}", response=r)
    return r.json(), r

# =========================
# SEARCH
# =========================
def safe_search(access_token, state):
    t=now()
    if t < state["search_block_until"]:
        print(f"🚦 search bloqueada {state['search_block_until']-t}s"); return
    if t - state["last_search_ts"] < 15*60 and state["queue"]: return

    query="(#crypto OR #bitcoin) -is:retweet -is:reply lang:en"
    print(f"🔎 Buscando: {query}")
    params={"query": query, "max_results": 10}
    if state["since_id"]: params["since_id"] = state["since_id"]
    try:
        data, resp = api_get("/tweets/search/recent", access_token, params)
        tweets = data.get("data", [])
        if tweets:
            ids=[t["id"] for t in tweets]  # nuevos→viejos
            existing=set(state["queue"])
            new_ids=[tid for tid in ids if tid not in existing]
            state["queue"]=new_ids + state["queue"]    # prioriza recientes
            state["since_id"]=max(ids, key=int)
            print(f"🧺 añadidos {len(new_ids)} (cola={len(state['queue'])})")
        else:
            print("😕 sin resultados nuevos")
        state["last_search_ts"]=now()
    except requests.HTTPError as e:
        r=e.response
        if r is not None and r.status_code==429:
            wait=seconds_until_reset(r)
            state["search_block_until"]=now()+wait
            print(f"⏳ 429 search, reintenta en ~{wait}s")
        else:
            print("❌ búsqueda:", str(e)[:300])

# =========================
# ACCIÓN: LIKE / BOOKMARK (con fallback auto)
# =========================
def act_on_tweet(access_token, user_id, tid, preferred="auto"):
    preferred = preferred.lower()
    def do_like():
        return api_post(f"/users/{user_id}/likes", access_token, {"tweet_id": tid})
    def do_bookmark():
        return api_post(f"/users/{user_id}/bookmarks", access_token, {"tweet_id": tid})

    if preferred == "like":
        return "like", do_like()
    if preferred == "bookmark":
        return "bookmark", do_bookmark()

    # auto: intenta like; si client-not-enrolled → bookmark
    try:
        return "like", do_like()
    except requests.HTTPError as e:
        txt = e.response.text if e.response is not None else ""
        if "client-not-enrolled" in txt:
            print("ℹ️ Like bloqueado por el plan (client-not-enrolled). Intentando bookmark…")
            return "bookmark", do_bookmark()
        raise

def act_one(access_token, user_id, state):
    if not state["queue"]: add_from_seed(state)
    if not state["queue"]:
        print("🪫 Cola vacía."); return

    # 1 acción cada ≥15 min (like o bookmark)
    wait=15*60 - (now()-state["last_like_ts"])
    if wait>0:
        print(f"⌛ Próxima acción en {wait}s"); return

    tid=state["queue"][0]
    print(f"➡️ Acción sobre {tid}… (preferencia: {ACTION})")
    try:
        which, (data, resp) = act_on_tweet(access_token, user_id, tid, preferred=ACTION)
        print(f"✅ {which.capitalize()} OK")
        state["queue"].pop(0)
        state["last_like_ts"]=now()
    except requests.HTTPError as e:
        r=e.response; body = r.text if r is not None else str(e)
        print("❌ Acción error:", body[:400])
        # si es problema del tweet (protegido/ya marcado), saltamos
        state["queue"].pop(0)

# =========================
# MAIN
# =========================
if __name__ == "__main__":
    try:
        access_token = get_access_token()
    except Exception as e:
        print("⚠️ Auth error:", e)
        print("Chequea: Redirect URI exacto, Type of App = Native App, Client ID correcto.")
        sys.exit(1)

    # Quién soy
    me_data, _ = api_get("/users/me", access_token)
    user = me_data.get("data", {})
    user_id = user.get("id"); username = user.get("username")
    print(f"👤 @{username} ({user_id})")

    st = load_state()
    safe_search(access_token, st)
    act_one(access_token, user_id, st)
    save_state(st)
    print(f"🏁 Cola restante: {len(st['queue'])}")
