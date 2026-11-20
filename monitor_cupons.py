import json
import os
import re
import smtplib
from email.mime.text import MIMEText
import requests
from bs4 import BeautifulSoup

TOKEN = os.environ["TELEGRAM_CUPONS_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
EMAIL_USER = os.environ.get("EMAIL_USER", "")
EMAIL_PASS = os.environ.get("EMAIL_PASS", "")
EMAIL_DESTINO = "marcusvaz.df@gmail.com"

ARQUIVO_HISTORICO = "historico_cupons.json"

FONTES = [
    {
        "loja": "Mercado Livre",
        "emoji": "🟡",
        "url": "https://www.cuponomia.com.br/desconto/mercado-livre",
    },
    {
        "loja": "Amazon",
        "emoji": "📦",
        "url": "https://www.cuponomia.com.br/desconto/amazon",
    },
    {
        "loja": "Shopee",
        "emoji": "🟠",
        "url": "https://www.cuponomia.com.br/desconto/shopee",
    },
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/129.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
}

def carregar_historico():
    if os.path.exists(ARQUIVO_HISTORICO):
        with open(ARQUIVO_HISTORICO, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def salvar_historico(historico):
    # Mantém os últimos 300 registros para o arquivo não crescer indefinidamente
    lista_limitada = list(historico)[-300:]
    with open(ARQUIVO_HISTORICO, "w", encoding="utf-8") as f:
        json.dump(lista_limitada, f, ensure_ascii=False, indent=2)

def enviar_telegram(mensagem):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": mensagem,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    requests.post(url, json=payload, timeout=10)

def enviar_email(assunto, corpo):
    if not EMAIL_USER or not EMAIL_PASS:
        return
    msg = MIMEText(corpo, "plain", "utf-8")
    msg["Subject"] = assunto
    msg["From"] = EMAIL_USER
    msg["To"] = EMAIL_DESTINO
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as servidor:
        servidor.login(EMAIL_USER, EMAIL_PASS)
        servidor.send_message(msg)

def buscar_cupons():
    historico = carregar_historico()
    novos_encontrados = 0

    for fonte in FONTES:
        try:
            resp = requests.get(fonte["url"], headers=HEADERS, timeout=20)
            if resp.status_code != 200:
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            blocos = soup.select("[data-coupon-code], .coupon-item, article")

            for bloco in blocos:
                texto = " ".join(bloco.get_text(" ", strip=True).split())
                if len(texto) < 15 or len(texto) > 260:
                    continue

                if not any(p in texto.lower() for p in ["off", "%", "r$", "frete", "cupom", "desconto"]):
                    continue

                codigo = bloco.get("data-coupon-code", "").strip()
                if not codigo:
                    match = re.search(r"\b([A-Z0-9]{4,18})\b", texto)
                    if match and any(c.isdigit() for c in match.group(1)):
                        codigo = match.group(1)

                chave_unica = f"{fonte['loja']}:{codigo or texto[:60]}"
                if chave_unica in historico:
                    continue

                historico.add(chave_unica)
                novos_encontrados += 1

                linha_codigo = f"🎟️ *Código:* `{codigo}`\n" if codigo else ""
                msg_tg = (
                    f"{fonte['emoji']} *NOVO CUPOM — {fonte['loja'].upper()}*\n\n"
                    f"{linha_codigo}"
                    f"📝 *Detalhe:* {texto[:180]}\n"
                    f"🔗 [Ver cupons da loja]({fonte['url']})"
                )
                enviar_telegram(msg_tg)

                if EMAIL_USER and EMAIL_PASS:
                    enviar_email(
                        f"🎟️ Cupom {fonte['loja']}: {codigo or 'Nova Oferta'}",
                        f"Loja: {fonte['loja']}\nCódigo: {codigo or 'Aplicado no link'}\nDetalhe: {texto}\nLink: {fonte['url']}",
                    )
        except Exception as erro:
            print(f"Erro ao consultar {fonte['loja']}: {erro}")

    if novos_encontrados > 0:
        salvar_historico(historico)

if __name__ == "__main__":
    buscar_cupons()
