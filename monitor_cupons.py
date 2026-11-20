import json
import os
import re
import smtplib
from email.mime.text import MIMEText
import xml.etree.ElementTree as ET
import requests

TOKEN = os.environ["TELEGRAM_CUPONS_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
EMAIL_USER = os.environ.get("EMAIL_USER", "")
EMAIL_PASS = os.environ.get("EMAIL_PASS", "")
EMAIL_DESTINO = "marcusvaz.df@gmail.com"

ARQUIVO_HISTORICO = "historico_cupons.json"

FEEDS_RSS = [
    "https://www.pelando.com.br/rss",
    "https://www.promobit.com.br/rss/ofertas.xml",
]

LOJAS_ALVO = {
    "mercado livre": "🟡 Mercado Livre",
    "mercadolivre": "🟡 Mercado Livre",
    "amazon": "📦 Amazon",
    "shopee": "🟠 Shopee",
}

TERMOS_CUPOM = ["cupom", "código", "codigo", "off", "desconto", "aplicar"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; RSSReader/1.0)",
    "Accept": "application/rss+xml, application/xml, text/xml",
}

def carregar_historico():
    if os.path.exists(ARQUIVO_HISTORICO):
        with open(ARQUIVO_HISTORICO, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def salvar_historico(historico):
    lista_limitada = list(historico)[-400:]
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

def identificar_loja(texto_lower):
    for chave, nome_formatado in LOJAS_ALVO.items():
        if chave in texto_lower:
            return nome_formatado
    return None

def extrair_codigo(texto):
    # Procura códigos em caixa alta típicos de cupom (ex: BLACK100, MELI20, SHOPEE15)
    candidatos = re.findall(r"\b([A-Z0-9]{4,18})\b", texto)
    ignorados = {"HTTP", "HTTPS", "HTML", "FREE", "PARA", "COM", "SEM", "OFF", "PIX", "APP", "PRIME", "FULL"}
    for c in candidatos:
        if c not in ignorados and (any(ch.isdigit() for ch in c) or len(c) >= 6):
            return c
    return ""

def buscar_cupons():
    primeira_execucao = not os.path.exists(ARQUIVO_HISTORICO)
    historico = carregar_historico()
    novos_encontrados = 0

    for feed_url in FEEDS_RSS:
        try:
            resp = requests.get(feed_url, headers=HEADERS, timeout=20)
            if resp.status_code != 200:
                print(f"Status {resp.status_code} em {feed_url}")
                continue

            root = ET.fromstring(resp.content)
            itens = root.findall(".//item")

            for item in itens:
                titulo = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                descricao_raw = item.findtext("description") or ""
                descricao = re.sub(r"<[^>]+>", " ", descricao_raw)
                descricao = " ".join(descricao.split())

                texto_completo = f"{titulo} {descricao}"
                texto_lower = texto_completo.lower()

                loja = identificar_loja(texto_lower)
                if not loja:
                    continue

                if not any(t in texto_lower for t in TERMOS_CUPOM):
                    continue

                chave_unica = link or titulo
                if chave_unica in historico:
                    continue

                historico.add(chave_unica)
                novos_encontrados += 1

                codigo = extrair_codigo(texto_completo)
                linha_codigo = f"🎟️ *Possível Código:* `{codigo}`\n" if codigo else ""

                msg_tg = (
                    f"{loja} — *CUPOM / OFERTA*\n\n"
                    f"{linha_codigo}"
                    f"📝 *Título:* {titulo}\n"
                    f"🔗 [Abrir oferta]({link})"
                )
                enviar_telegram(msg_tg)

                if EMAIL_USER and EMAIL_PASS:
                    enviar_email(
                        f"🎟️ {loja}: {codigo or titulo[:50]}",
                        f"Loja: {loja}\nCódigo: {codigo or 'Ver no link'}\nTítulo: {titulo}\nDetalhes: {descricao[:300]}\nLink: {link}",
                    )
        except Exception as erro:
            print(f"Erro ao ler {feed_url}: {erro}")

    if novos_encontrados > 0 or primeira_execucao:
        salvar_historico(historico)

    if primeira_execucao:
        enviar_telegram(
            f"✅ *Monitor de Cupons ativado!*\n"
            f"Cupons encontrados nesta primeira varredura: *{novos_encontrados}*.\n"
            f"A partir de agora você receberá apenas cupons inéditos a cada 15 minutos."
        )

if __name__ == "__main__":
    buscar_cupons()
