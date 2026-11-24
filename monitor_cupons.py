import json
import os
import re
import urllib.parse
import requests
from bs4 import BeautifulSoup

TOKEN = os.environ.get("TELEGRAM_CUPONS_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

ARQUIVO_HISTORICO = "historico_cupons.json"

CANAIS_TELEGRAM = [
    "soconsolespromonautas",
    "descontoemgames",
    "ofertasgames",
    "economizagames",
    "rochacupons",
    "nerdcupons",
    "pelando",
    "promobit",
    "gatry",
    "ofertaseshopee",
    "cuponsmercadolivre",
    "ofertasamazonbr",
    "hardmob_promocoes",
    "urubudospromos",
    "pechinchou",
    "promocoestech",
]

BUSCAS_AGREGADORES = [
    "ps5 slim",
    "playstation 5 slim",
    "lg dual inverter 9000",
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
    "magalu": "🔵 Magalu",
    "kabum": "🟠 KaBuM!",
    "casas bahia": "🔵 Casas Bahia",
    "fast shop": "🔴 Fast Shop",
}

PALAVRAS_IGNORADAS = {
    "HTTP", "HTTPS", "HTML", "FREE", "PARA", "COM", "SEM", "OFF",
    "PIX", "APP", "PRIME", "FULL", "LINK", "AQUI", "HOJE", "AGORA",
    "LOJA", "MAIS", "GRATIS", "FRETE", "LISTA", "CLIQUE", "VALIDO",
    "ACIMA", "LIMITE", "CUPOM", "CUPONS", "NOVO", "CORRE", "AMAZON",
    "SHOPEE", "MERCADO", "LIVRE", "OFERTA", "OFERTAS", "GRUPO", "GRUPOS",
    "HDR10", "FHD", "UHD", "QLED", "OLED", "DLED", "SMART", "WIFI",
    "HDMI", "USB", "BIVOLT", "110V", "220V", "PRETO", "BRANCO",
    "APLIQUE", "RESGATE", "COPIE", "USE", "CODIGO", "DESCONTO",
    "DISPONIVEL", "ESGOTADO", "ATENCAO", "PESSOAL", "BOT", "PRECO", "PRECOS"
}

PADRAO_HARDWARE = re.compile(
    r"^(\d+(GB|TB|MB|HZ|W|V|ML|KG|HDMI|USB|MP|MAH)|.*(GBRAM|HDMI|HDR|OLED|QLED|DLED|BIVOLT).*)$"
)

LINHAS_LIXO = [
    "mais grupos", "nerdofertas.com", "clique \"mostrar mais\"",
    "entre no grupo", "canal de ofertas", "participe do", "siga nosso",
    "monitorar preço deste produto", "vocês sabiam que temos um"
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
        try:
            with open(ARQUIVO_HISTORICO, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

def salvar_historico(historico):
    lista_limitada = list(historico)[-1500:]
    with open(ARQUIVO_HISTORICO, "w", encoding="utf-8") as f:
        json.dump(lista_limitada, f, ensure_ascii=False, indent=2)

def enviar_telegram(mensagem):
    if not TOKEN or not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": mensagem,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    requests.post(url, json=payload, timeout=10)

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

def extrair_menor_preco(texto):
    # Captura valores no padrão R$ 3.875,00 ou R$ 3875,90 (ignora parcelas como "15x de R$313")
    texto_sem_parcelas = re.sub(r"\d+\s*x\s*(?:de\s*)?r\$\s*[\d.,]+", "", texto, flags=re.IGNORECASE)
    matches = re.findall(r"r\$\s*(\d{1,2}\.?\d{3}(?:,\d{2})?)", texto_sem_parcelas, flags=re.IGNORECASE)
    valores = []
    for m in matches:
        num_str = m.replace(".", "").replace(",", ".")
        try:
            val = float(num_str)
            if val >= 1000:
                valores.append(val)
        except ValueError:
            pass
    return min(valores) if valores else None

def avaliar_oferta_alvo(texto_bruto, texto_lower):
    # Ignora avisos institucionais do canal
    if any(aviso in texto_lower for aviso in ["vocês sabiam que temos um", "bot que monitora", "atenção, pessoal"]):
        return None, None

    menor_preco = extrair_menor_preco(texto_bruto)
    if not menor_preco:
        return None, None

    # 1) Avaliação PS5
    tem_ps5 = any(k in texto_lower for k in ["ps5", "playstation 5"])
    eh_console_ps5 = (
        tem_ps5
        and any(k in texto_lower for k in ["console", "slim", "bundle", "825gb", "1tb", "leitor", "digital"])
        and not any(x in texto_lower for x in ["jogo ", "midia fisica", "mídia física", "capa ", "suporte ", "grip", "pelicula", "película", "controle dualsense"])
    )

    if eh_console_ps5:
        eh_digital = "digital" in texto_lower and "com leitor" not in texto_lower
        if eh_digital:
            # Só avisa PS5 Digital se estiver até R$ 3.600,00 (para fechar <= R$ 4.050 com leitor avulso)
            if 2500 <= menor_preco <= 3600.00:
                chave_dedup = f"ps5_digital:{int(menor_preco)}"
                return f"🎮 PS5 SLIM DIGITAL POR R$ {menor_preco:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."), chave_dedup
        else:
            # PS5 Slim com Leitor: avisa até R$ 4.050,00
            if 2800 <= menor_preco <= 4050.00:
                chave_dedup = f"ps5_leitor:{int(menor_preco)}"
                return f"🎮 PS5 SLIM COM LEITOR POR R$ {menor_preco:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."), chave_dedup
        return None, None

    # 2) Avaliação Ar Condicionado LG Dual Inverter 9000 BTUs
    eh_ar_lg = (
        "lg" in texto_lower
        and "9000" in texto_lower
        and any(k in texto_lower for k in ["inverter", "ar condicionado", "ar-condicionado", "compact"])
    )

    if eh_ar_lg and 1300 <= menor_preco <= 1950.00:
        chave_dedup = f"ar_lg_9000:{int(menor_preco)}"
        return f"❄️ AR LG 9000 BTUs POR R$ {menor_preco:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."), chave_dedup

    return None, None

def codigo_valido(cand, veio_de_tag_code=False):
    if not re.fullmatch(r"[A-Z0-9]{4,20}", cand):
        return False
    if cand in PALAVRAS_IGNORADAS or cand.isdigit():
        return False
    if PADRAO_HARDWARE.match(cand):
        return False
    # Se não veio de bloco copiável (<code>/<pre>), exige ao menos 1 número para evitar palavras soltas (ex: APLIQUE, CORRE)
    if not veio_de_tag_code and not re.search(r"\d", cand):
        return False
    return True

def limpar_linhas(texto_bruto):
    linhas_limpas = []
    for linha in texto_bruto.splitlines():
        l = linha.strip()
        if not l:
            continue
        l_lower = l.lower()
        if l_lower.startswith("http") or any(lixo in l_lower for lixo in LINHAS_LIXO):
            continue
        sem_simbolos = re.sub(r"[^\w\s%$,.:;!?()-]", "", l).strip()
        if len(sem_simbolos) >= 2:
            linhas_limpas.append(sem_simbolos)
    return linhas_limpas

def extrair_cupons_estruturados(bloco_html, texto_bruto):
    linhas = limpar_linhas(texto_bruto)
    codigos_encontrados = []

    for tag in bloco_html.find_all(["code", "pre"]):
        cand = tag.get_text(strip=True).upper()
        if codigo_valido(cand, veio_de_tag_code=True) and cand not in codigos_encontrados:
            codigos_encontrados.append(cand)

    gatilhos = re.compile(
        r"(?:cupom|c[oó]digo|use|aplique|resgate|limite\s+r\$\s*\d+\s*off)\s*[:\-]?\s*([A-Z0-9]{4,20})\b",
        re.IGNORECASE,
    )
    for idx, linha in enumerate(linhas):
        for match in gatilhos.findall(linha):
            cand = match.upper()
            if codigo_valido(cand, veio_de_tag_code=False) and cand not in codigos_encontrados:
                codigos_encontrados.append(cand)

        if idx > 0 and re.search(r"(cupom|c[oó]digo|aplique|resgate)\s*[:\-]?\s*$", linhas[idx - 1], re.IGNORECASE):
            cand = linha.strip().upper()
            if codigo_valido(cand, veio_de_tag_code=False) and cand not in codigos_encontrados:
                codigos_encontrados.append(cand)

    if not codigos_encontrados:
        return []

    resultados = []
    for codigo in codigos_encontrados:
        regra = ""
        for idx, linha in enumerate(linhas):
            if codigo in linha.upper():
                contexto = []
                for ant in linhas[max(0, idx - 2):idx]:
                    if any(k in ant.lower() for k in ["off", "%", "r$", "acima", "limite", "desconto", "mínimo", "minimo"]):
                        contexto.append(ant)
                resto_linha = re.sub(re.escape(codigo), "", linha, flags=re.IGNORECASE).strip(" :-•|")
                if resto_linha and len(resto_linha) > 3:
                    contexto.append(resto_linha)
                regra = " | ".join(contexto)
                break

        if not regra:
            for linha in linhas:
                if any(k in linha.lower() for k in ["off", "%", "desconto"]):
                    regra = linha
                    break

        resultados.append((codigo, regra[:140] if regra else "Cupom ativo (conferir regras no link)"))

    return resultados

def varrer_pelando_direto(historico):
    alterou = False
    for termo in BUSCAS_AGREGADORES:
        q = urllib.parse.quote(termo)
        url = f"https://www.pelando.com.br/busca/{q}"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            for a in soup.select("a[href*='/d/']")[:8]:
                href = a.get("href", "")
                titulo = a.get_text(" ", strip=True)
                if not href or len(titulo) < 10:
                    continue
                link_completo = f"https://www.pelando.com.br{href}" if href.startswith("/") else href
                titulo_alerta, chave_dedup = avaliar_oferta_alvo(titulo, titulo.lower())
                if not titulo_alerta or not chave_dedup:
                    continue
                if chave_dedup in historico:
                    continue
                historico.add(chave_dedup)
                alterou = True
                msg = (
                    f"🚨 <b>{escapar_html(titulo_alerta)} (Pelando)</b>\n"
                    f"📌 {escapar_html(titulo[:160])}\n"
                    f"🔗 <a href=\"{link_completo}\">Ver oferta no Pelando</a>"
                )
                enviar_telegram(msg)
        except Exception as erro:
            print(f"Erro Pelando ({termo}): {erro}")
    return alterou

def buscar_cupons():
    historico = carregar_historico()
    houve_novos = False

    if varrer_pelando_direto(historico):
        houve_novos = True

    for canal in CANAIS_TELEGRAM:
        canal_limpo = canal.lstrip("@").strip()
        url_canal = f"https://t.me/s/{canal_limpo}"

        try:
            resp = requests.get(url_canal, headers=HEADERS, timeout=20)
            if resp.status_code != 200:
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            mensagens = soup.select(".tgme_widget_message_wrap")
            if not mensagens:
                continue

            for msg_wrap in mensagens[-15:]:
                msg_div = msg_wrap.select_one(".tgme_widget_message")
                texto_div = msg_wrap.select_one(".tgme_widget_message_text")
                if not msg_div or not texto_div:
                    continue

                post_id = msg_div.get("data-post", "")
                texto_bruto = texto_div.get_text("\n", strip=True)
                texto_lower = texto_bruto.lower()
                link_post = f"https://t.me/{post_id}" if post_id else url_canal

                # 1) Alerta prioritário de oferta dentro da faixa de preço alvo
                titulo_alerta, chave_dedup = avaliar_oferta_alvo(texto_bruto, texto_lower)
                if titulo_alerta and chave_dedup:
                    if chave_dedup not in historico:
                        historico.add(chave_dedup)
                        houve_novos = True
                        linhas_resumo = limpar_linhas(texto_bruto)[:5]
                        resumo_formatado = "\n".join(linhas_resumo)
                        msg_oferta = (
                            f"🚨 <b>{escapar_html(titulo_alerta)}</b>\n"
                            f"{escapar_html(resumo_formatado)}\n"
                            f"🔗 <a href=\"{link_post}\">Abrir postagem original</a> (via @{escapar_html(canal_limpo)})"
                        )
                        enviar_telegram(msg_oferta)

                # 2) Extração normal de cupons reais
                loja = identificar_loja(texto_lower)
                if not loja:
                    continue

                pares_cupons = extrair_cupons_estruturados(texto_div, texto_bruto)
                if not pares_cupons:
                    continue

                for codigo, regra in pares_cupons:
                    chave_unica = f"cupom:{loja}:{codigo}"
                    if chave_unica in historico:
                        continue

                    historico.add(chave_unica)
                    houve_novos = True

                    msg_tg = (
                        f"{loja} — 🎟️ <code>{escapar_html(codigo)}</code>\n"
                        f"📌 {escapar_html(regra)}\n"
                        f"🔗 <a href=\"{link_post}\">Abrir oferta</a> (via @{escapar_html(canal_limpo)})"
                    )
                    enviar_telegram(msg_tg)

        except Exception as erro:
            print(f"Erro ao ler @{canal_limpo}: {erro}")

    if houve_novos:
        salvar_historico(historico)

if __name__ == "__main__":
    buscar_cupons()
