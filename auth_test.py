import os
import tweepy
import time
from dotenv import load_dotenv
from pathlib import Path

# ===========================================================
# 1. Cargar credenciales
# ===========================================================
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)

API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
ACCESS_SECRET = os.getenv("ACCESS_SECRET")

# ===========================================================
# 2. Inicializar cliente v2 (User Context)
# ===========================================================
client = tweepy.Client(
    consumer_key=API_KEY,
    consumer_secret=API_SECRET,
    access_token=ACCESS_TOKEN,
    access_token_secret=ACCESS_SECRET,
    wait_on_rate_limit=True
)

# ===========================================================
# 3. Inicializar API v1.1 (para bloquear)
# ===========================================================
auth = tweepy.OAuth1UserHandler(API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_SECRET)
api_v1 = tweepy.API(auth, wait_on_rate_limit=True)

# ===========================================================
# 4. Autenticación
# ===========================================================
try:
    me = client.get_me()
    user = me.data
    print("✅ Autenticación correcta")
    print(f"👤 Usuario: @{user.username}")
    print(f"🆔 ID de usuario: {user.id}\n")
except Exception as e:
    print("❌ Error de autenticación:", e)
    exit()

# ===========================================================
# 5. Función para mostrar headers de rate limit
# ===========================================================
def show_rate_info(response):
    """Muestra los encabezados de límite (si existen)."""
    try:
        headers = response.headers
        limit = headers.get("x-rate-limit-limit", "N/A")
        remaining = headers.get("x-rate-limit-remaining", "N/A")
        reset = headers.get("x-rate-limit-reset", "N/A")
        print(f"📊 Límite total: {limit} | Restantes: {remaining} | Reinicio: {reset}\n")
    except Exception:
        print("❔ No se encontraron encabezados de límite.\n")

# ===========================================================
# 6. Función genérica para probar endpoints
# ===========================================================
def test_action(name, func):
    try:
        response = func()
        print(f"✅ Acción '{name}' ejecutada exitosamente.\n")
        if hasattr(response, "meta"):
            print("📋 Meta:", response.meta)
        if hasattr(response, "__dict__") and "headers" in response.__dict__:
            show_rate_info(response)
    except tweepy.errors.Forbidden as e:
        print(f"🚫 Acción '{name}' denegada (403 Forbidden).")
        show_rate_info(e.response)
    except tweepy.errors.TooManyRequests as e:
        print(f"⚠️ Límite de velocidad alcanzado para '{name}'.")
        show_rate_info(e.response)
        reset = e.response.headers.get("x-rate-limit-reset")
        if reset:
            wait = max(int(reset) - int(time.time()), 0)
            print(f"⏳ Esperando {wait} segundos hasta el reinicio.\n")
    except Exception as e:
        print(f"❌ Error en '{name}':", e)

# ===========================================================
# 7. Definir acciones de prueba
# ===========================================================
def like_test():
    return client.like(tweet_id="20")

def follow_test():
    return client.follow_user(target_user_id="12")

def block_test():
    return api_v1.create_block(user_id="12")  # v1.1

def retweet_test():
    return client.retweet(tweet_id="20")

# ===========================================================
# 8. Ejecutar pruebas
# ===========================================================
print("🔍 Verificando accesos y límites por endpoint:\n")
actions = [
    ("Like", like_test),
    ("Follow", follow_test),
    ("Block", block_test),
    ("Retweet", retweet_test),
]
for name, func in actions:
    test_action(name, func)
