import tweepy
import os
from dotenv import load_dotenv
from pathlib import Path

# Cargar variables de entorno
env_path = Path(__file__).resolve().parent / '.env'
load_dotenv(dotenv_path=env_path, override=True)

# Credenciales OAuth 2.0 (User Context)
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
ACCESS_SECRET = os.getenv("ACCESS_SECRET")

# Crear cliente Tweepy para API v2 (Free Tier compatible)
client = tweepy.Client(
    consumer_key=API_KEY,
    consumer_secret=API_SECRET,
    access_token=ACCESS_TOKEN,
    access_token_secret=ACCESS_SECRET
)

# Tweet de prueba
try:
    response = client.create_tweet(text="🚀 Tweet de prueba publicado con la API gratuita de X (2025).")
    print(f"✅ Tweet publicado correctamente. ID del tweet: {response.data['id']}")
except tweepy.errors.Forbidden as e:
    print("❌ Error de permisos:", e)
    print("Tu App necesita permisos de escritura (Read and Write) en el portal de desarrollador.")
except Exception as e:
    print("❌ Otro error al publicar el tweet:", e)
