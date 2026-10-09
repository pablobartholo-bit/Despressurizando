
import os
import json
import time
import datetime
import urllib.request
import urllib.parse
import urllib.error

# Configuracoes
YOUTUBE_KEY = os.environ["YOUTUBE_API_KEY"]
SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_SECRET_KEY"]

# Consultas iniciais para validar a coleta
QUERIES = [
    "FPSO offshore Brasil",
    "inspeção de equipamentos NR 13",
]


def request_json(url, headers=None, method="GET", payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None

    req = urllib.request.Request(
        url,
        data=data,
        headers=headers or {},
        method=method,
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)

    except urllib.error.HTTPError as erro:
        detalhe = erro.read().decode("utf-8", errors="replace")
        print(f"Erro na API: HTTP {erro.code} | {detalhe[:1000]}")
        raise


def yt(resource, params):
    parametros = dict(params)
    parametros["key"] = YOUTUBE_KEY

    url = (
        "https://www.googleapis.com/youtube/v3/"
        + resource
        + "?"
        + urllib.parse.urlencode(parametros)
    )

    return request_json(url)


def upsert(table, rows, conflict="id"):
    if not rows:
        print(f"Supabase: nenhuma linha para {table}.")
        return

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": "Bearer " + SUPABASE_KEY,
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }

    url = (
        SUPABASE_URL
        + "/rest/v1/"
        + table
        + "?on_conflict="
        + urllib.parse.quote(conflict)
    )

    data = json.dumps(rows).encode("utf-8")

    for tentativa in range(1, 4):
        req = urllib.request.Request(
            url,
            data=data,
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                response.read()

            print(
                f"Supabase: {table} gravada com sucesso "
                f"({len(rows)} registros)."
            )
            return

        except urllib.error.HTTPError as erro:
            detalhe = erro.read().decode(
                "utf-8",
                errors="replace",
            )

            print(
                f"Supabase | tabela={table} | "
                f"HTTP {erro.code} | "
                f"tentativa={tentativa}/3 | "
                f"resposta={detalhe[:1000]}"
            )

            if erro.code not in (429, 500, 502, 503, 504):
                raise

            if tentativa == 3:
                raise

        except urllib.error.URLError as erro:
            print(
                f"Supabase | tabela={table} | "
                f"erro de conexao | "
                f"tentativa={tentativa}/3 | "
                f"detalhe={erro.reason}"
            )

            if tentativa == 3:
                raise

        time.sleep(2 ** tentativa)


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    today = now.date().isoformat()

    found = {}

    print("Iniciando coleta de videos do YouTube...")

    for query in QUERIES:
        print(f"Pesquisando: {query}")

        results = yt(
            "search",
            {
                "part": "snippet",
                "type": "video",
                "q": query,
                "maxResults": 5,
                "order": "relevance",
            },
        )

        for item in results.get("items", []):
            video_id = item.get("id", {}).get("videoId")

            if video_id:
                found[video_id] = query

    if not found:
        raise RuntimeError(
            "Nenhum video retornado pela API do YouTube."
        )

    details = yt(
        "videos",
        {
            "part": "snippet,statistics,contentDetails",
            "id": ",".join(found.keys()),
        },
    ).get("items", [])

    if not details:
        raise RuntimeError(
            "Nao foi possivel obter detalhes dos videos."
        )

    channel_ids = sorted(
        {
            v["snippet"]["channelId"]
            for v in details
        }
    )

    channels_raw = yt(
        "channels",
        {
            "part": "snippet,statistics,contentDetails",
            "id": ",".join(channel_ids),
        },
    ).get("items", [])

    channels = []
    channel_history = []

    for c in channels_raw:
        stats = c.get("statistics", {})

        count = (
            None
            if stats.get("hiddenSubscriberCount")
            else int(stats.get("subscriberCount", 0))
        )

        channels.append(
            {
                "id": c["id"],
                "name": c["snippet"]["title"],
                "url": "https://www.youtube.com/channel/" + c["id"],
                "created_at_youtube": c["snippet"].get("publishedAt"),
                "subscriber_count": count,
                "video_count": int(stats.get("videoCount", 0)),
                "collected_at": now.isoformat(),
            }
        )

        channel_history.append(
            {
                "channel_id": c["id"],
                "collected_date": today,
                "subscriber_count": count,
                "video_count": int(stats.get("videoCount", 0)),
            }
        )

    videos = []
    video_history = []

    for v in details:
        stats = v.get("statistics", {})

        views = int(stats.get("viewCount", 0))

        likes = (
            int(stats["likeCount"])
            if "likeCount" in stats
            else None
        )

        videos.append(
            {
                "id": v["id"],
                "channel_id": v["snippet"]["channelId"],
                "title": v["snippet"]["title"],
                "url": "https://www.youtube.com/watch?v=" + v["id"],
                "published_at": v["snippet"]["publishedAt"],
                "view_count": views,
                "like_count": likes,
                "niche": found[v["id"]],
                "collected_at": now.isoformat(),
            }
        )

        video_history.append(
            {
                "video_id": v["id"],
                "collected_date": today,
                "view_count": views,
                "like_count": likes,
            }
        )

    print("Gravando dados no Supabase...")

    upsert("channels", channels)
    upsert("videos", videos)

    upsert(
        "channel_metrics_history",
        channel_history,
        "channel_id,collected_date",
    )

    upsert(
        "video_metrics_history",
        video_history,
        "video_id,collected_date",
    )

    print(
        f"Coleta concluida: "
        f"{len(channels)} canais e "
        f"{len(videos)} videos."
    )


if __name__ == "__main__":
    main()
