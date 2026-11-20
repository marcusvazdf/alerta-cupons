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
    "nerdcupons",
    "pelando",
    "promobit",
    "gatry",
    "descontoemgames",
    "ofertaseshopee",
    "cuponsmercadolivre",
    "ofertasamazonbr",
    "hardmob_promocoes",
]

LOJAS_ALVO = {
    "mercado livre": "🟡 Mercado Livre",
    "mercadolivre": "🟡 Mercado Livre",
    "meli.la": "🟡 Mercado Livre",
    "meli": "🟡 Mercado Livre",
    "amazon": "📦 Amazon",
    "amzn": "📦 Amazon",
    "shopee": "🟠 Shopee",
    "shope": "🟠 Shopee",
}

PALAVRAS_IGNORADAS = {
    "HTTP", "HTTPS", "HTML", "FREE", "PARA", "COM", "SEM", "OFF",
    "PIX", "APP", "PRIME", "FULL", "LINK", "AQUI", "HOJE", "AGORA",
    "LOJA", "MAIS", "GRATIS", "FRETE", "LISTA", "CLIQUE", "VALIDO",
    "ACIMA", "LIMITE", "CUPOM", "CUPONS", "NOVO", "CORRE", "AMAZON",
    "SHOPEE", "MERCADO", "LIVRE", "OFERTA", "OFERTAS", "GRUPO", "GRUPOS"
}

LINHAS_LIXO = [
    "mais grupos", "nerdofertas.com", "clique \"mostrar mais\"",
    "entre no grupo", "canal de ofertas", "participe do", "siga nosso"
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
    lista_limitada = list(historico)[-800:]
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

def escapar_html(texto):
    return (
        texto.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )

def limpar_linhas(texto_bruto):
    linhas_limpas = []
    for linha in texto_bruto.splitlines():
        l = linha.strip()
        if not l:
            continue
        l_lower = l.lower()
        # Remove URLs soltas e rodapés de divulgação de grupos
        if l_lower.startswith("http") or any(lixo in l_lower for lixo in LINHAS_LIXO):
            continue
        # Remove emojis isolados na linha
        sem_simbolos = re.sub(r"[^\w\s%$,.:;!?()-]", "", l).strip()
        if len(sem_simbolos) < 2:
            continue
        linhas_limpas.append(sem_simbolos)
    return linhas_limpas

def extrair_cupons_estruturados(bloco_html, texto_bruto):
    """
    Retorna lista de tuplas (codigo, regra_resumida).
    Descarta posts que não possuem código real de cupom.
    """
    linhas = limpar_linhas(texto_bruto)
    codigos_encontrados = []

    # 1. Prioridade: tags <code> ou <pre> (padrão do Telegram para cupons copiáveis)
    for tag in bloco_html.find_all(["code", "pre"]):
        cand = tag.get_text(strip=True).upper()
        if re.fullmatch(r"[A-Z0-9]{4,20}", cand) and cand not in PALAVRAS_IGNORADAS:
            if cand not in codigos_encontrados:
                codigos_encontrados.append(cand)

    # 2. Busca códigos em caixa alta no texto (ex: MOVEIS2011, BLACK100, CUPOM15)
    for linha in linhas:
        # Ignora linhas que parecem modelo de produto (ex: 748ml, B01zrah4i, 12000)
        if re.search(r"\b\d+(ml|g|kg|gb|tb|btu|v|w|cm|mm)\b", linha.lower()):
            continue
        for match in re.findall(r"\b([A-Z0-9]{5,18})\b", linha):
            if match in PALAVRAS_IGNORADAS or match.isdigit():
                continue
            # Precisa ter letras e números OU ter contexto explícito de cupom na linha
            tem_letra_e_num = any(c.isalpha() for c in match) and any(c.isdigit() for c in match)
            contexto_cupom = any(p in linha.lower() for p in ["cupom", "código", "codigo", "off", "limite", "acima de", "use"])
            if (tem_letra_e_num or contexto_cupom) and match not in codigos_encontrados:
                codigos_encontrados.append(match)

    if not codigos_encontrados:
        return []

    resultados = []
    for codigo in codigos_encontrados:
        regra = ""
        for idx, linha in enumerate(linhas):
            if codigo in linha:
                # Junta até 2 linhas imediatamente anteriores que tragam % OFF ou valor mínimo
                contexto = []
                for ant in linhas[max(0, idx - 2):idx]:
                    if any(k in ant.lower() for k in ["off", "%", "r$", "acima", "limite", "desconto", "mínimo", "minimo"]):
                        contexto.append(ant)
                # Também aproveita texto da própria linha sem o código
                resto_linha = linha.replace(codigo, "").strip(" :-•|")
                if resto_linha and len(resto_linha) > 3:
                    contexto.append(resto_linha)
                regra = " | ".join(contexto)
                break

        if not regra:
            # Pega a primeira linha que mencione desconto ou valor
            for linha in linhas:
                if any(k in linha.lower() for k in ["off", "%", "r$", "desconto"]):
                    regra = linha
                    break

        resultados.append((codigo, regra[:140] if regra else "Cupom ativo (conferir regras no link)"))

    return resultados

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
                texto_bruto = texto_div.get_text("\n", strip=True)
                loja = identificar_loja(texto_bruto.lower())
                if not loja:
                    continue

                pares_cupons = extrair_cupons_estruturados(texto_div, texto_bruto)
                if not pares_cupons:
                    continue

                link_post = f"https://t.me/{post_id}" if post_id else url_canal

                for codigo, regra in pares_cupons:
                    # Deduplica pelo par Loja + Código (evita receber o mesmo cupom de 5 canais diferentes)
                    chave_unica = f"cupom:{loja}:{codigo}"
                    if chave_unica in historico:
                        continue

                    historico.add(chave_unica)

                    msg_tg = (
                        f"{loja} — 🎟️ <code>{escapar_html(codigo)}</code>\n"
                        f"📌 {escapar_html(regra)}\n"
                        f"🔗 <a href=\"{link_post}\">Abrir oferta</a> (via @{escapar_html(canal_limpo)})"
                    )
                    enviar_telegram(msg_tg)

                    bloco_email = (
                        f"{loja} | Cupom: {codigo}\n"
                        f"Regra: {regra}\n"
                        f"Link: {link_post} (via @{canal_limpo})\n"
                        f"----------------------------------------"
                    )
                    novos_cupons_email.append(bloco_email)

        except Exception as erro:
            print(f"Erro ao ler @{canal_limpo}: {erro}")

    if novos_cupons_email:
        salvar_historico(historico)
        qtd = len(novos_cupons_email)
        enviar_email(
            f"🎟️ {qtd} {'novo cupom' if qtd == 1 else 'novos cupons'} (ML / Amazon / Shopee)",
            "Cupons inéditos capturados:\n\n" + "\n".join(novos_cupons_email),
        )

if __name__ == "__main__":
    buscar_cupons()
