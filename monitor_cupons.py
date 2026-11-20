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

CANAIS_TELEGRAM = [
    "rochacupons",
    "pelando",
    "promobit",
    "gatry",
    "descontoemgames",
    "ofertaseshopee",
    "cuponsmercadolivre",
    "ofertasamazonbr",
    "hardmob_promocoes",
    "nerdcupons",
]

LOJAS_ALVO = {
    "mercado livre": "🟡 Mercado Livre",
    "mercadolivre": "🟡 Mercado Livre",
    "meli": "🟡 Mercado Livre",
    "amazon": "📦 Amazon",
    "shopee": "🟠 Shopee",
}

TERMOS_CUPOM = [
    "cupom", "cupons", "código", "codigo", "use o", "aplique",
    "resgate", "% off", "reais off", "r$ ", "desconto"
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
    lista_limitada = list(historico)[-600:]
    with open(ARQUIVO_HISTORICO, "w", encoding="utf-8") as f:
        json.dump(lista_limitada, f, ensure_ascii=False, indent=2)

def enviar_telegram(mensagem):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": mensagem,
        "parse_mode": "HTML",
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

def identificar_loja(texto_lower):
    for chave, nome_formatado in LOJAS_ALVO.items():
        if chave in texto_lower:
            return nome_formatado
    return None

def extrair_codigo(bloco_html, texto_limpo):
    for tag_code in bloco_html.find_all(["code", "pre"]):
        cand = tag_code.get_text(strip=True)
        if 3 <= len(cand) <= 25 and " " not in cand:
            return cand

    candidatos = re.findall(r"\b([A-Z0-9]{4,20})\b", texto_limpo)
    ignorados = {
        "HTTP", "HTTPS", "HTML", "FREE", "PARA", "COM", "SEM", "OFF",
        "PIX", "APP", "PRIME", "FULL", "LINK", "AQUI", "HOJE", "AGORA", "LOJA"
    }
    for c in candidatos:
        if c not in ignorados and (any(ch.isdigit() for ch in c) or len(c) >= 6):
            return c
    return ""

def escapar_html(texto):
    return (
        texto.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )

def buscar_cupons():
    historico = carregar_historico()
    novos_cupons_email = []

    for canal in CANAIS_TELEGRAM:
        canal_limpo = canal.lstrip("@").strip()
        url_canal = f"https://t.me/s/{canal_limpo}"

        try:
            resp = requests.get(url_canal, headers=HEADERS, timeout=20)
            if resp.status_code != 200:
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            mensagens = soup.select(".tgme_widget_message_wrap")

            for msg_wrap in mensagens[-12:]:
                msg_div = msg_wrap.select_one(".tgme_widget_message")
                texto_div = msg_wrap.select_one(".tgme_widget_message_text")
                if not msg_div or not texto_div:
                    continue

                post_id = msg_div.get("data-post", "")
                texto_limpo = texto_div.get_text("\n", strip=True)
                texto_lower = texto_limpo.lower()

                loja = identificar_loja(texto_lower)
                if not loja:
                    continue

                if not any(t in texto_lower for t in TERMOS_CUPOM):
                    continue

                codigo = extrair_codigo(texto_div, texto_limpo)
                chave_unica = f"tg:{post_id}" if post_id else f"tg:{canal_limpo}:{texto_limpo[:60]}"

                if chave_unica in historico:
                    continue

                historico.add(chave_unica)

                link_post = f"https://t.me/{post_id}" if post_id else url_canal
                resumo = escapar_html(texto_limpo[:450])
                linha_codigo = f"🎟️ <b>Cupom:</b> <code>{escapar_html(codigo)}</code>\n" if codigo else ""

                # Envia individualmente no Telegram (rápido e fácil de copiar com 1 toque)
                msg_tg = (
                    f"{loja} — <b>NOVO CUPOM</b>\n"
                    f"📡 <i>Fonte: @{escapar_html(canal_limpo)}</i>\n\n"
                    f"{linha_codigo}"
                    f"📝 {resumo}\n\n"
                    f"🔗 <a href=\"{link_post}\">Ver mensagem original</a>"
                )
                enviar_telegram(msg_tg)

                # Guarda para enviar tudo em um único e-mail consolidado
                bloco_email = (
                    f"========================================\n"
                    f"{loja} | Fonte: @{canal_limpo}\n"
                    f"Cupom: {codigo or 'Aplicado no link'}\n"
                    f"Detalhes:\n{texto_limpo}\n"
                    f"Link: {link_post}\n"
                )
                novos_cupons_email.append(bloco_email)

        except Exception as erro:
            print(f"Erro ao ler @{canal_limpo}: {erro}")

    if novos_cupons_email:
        salvar_historico(historico)

        qtd = len(novos_cupons_email)
        assunto = f"🎟️ Resumo de Cupons: {qtd} {'novo cupom encontrado' if qtd == 1 else 'novos cupons encontrados'}"
        corpo = (
            f"O robô encontrou {qtd} {'novo cupom' if qtd == 1 else 'novos cupons'} nesta verificação:\n\n"
            + "\n".join(novos_cupons_email)
        )
        enviar_email(assunto, corpo)

if __name__ == "__main__":
    buscar_cupons()
