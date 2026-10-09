import os, json, datetime, urllib.request, urllib.parse

YOUTUBE_KEY = os.environ['YOUTUBE_API_KEY']
SUPABASE_URL = os.environ['SUPABASE_URL'].rstrip('/')
SUPABASE_KEY = os.environ['SUPABASE_SECRET_KEY']

# Canais e vídeos reais devem ser adicionados após o teste inicial.
# Este primeiro teste consulta vídeos por palavra-chave e registra seus canais.
QUERIES = ['FPSO offshore Brasil', 'inspeção de equipamentos NR 13']

def request_json(url, headers=None, method='GET', payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)

def yt(resource, params):
    params['key'] = YOUTUBE_KEY
    return request_json('https://www.googleapis.com/youtube/v3/' + resource + '?' + urllib.parse.urlencode(params))

def upsert(table, rows, conflict='id'):
    if not rows:
        return
    headers = {
        'apikey': SUPABASE_KEY,
        'Authorization': 'Bearer ' + SUPABASE_KEY,
        'Content-Type': 'application/json',
        'Prefer': 'resolution=merge-duplicates,return=minimal'
    }
    req = urllib.request.Request(
        SUPABASE_URL + '/rest/v1/' + table + '?on_conflict=' + urllib.parse.quote(conflict),
        data=json.dumps(rows).encode(), headers=headers, method='POST'
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        response.read()

def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    today = now.date().isoformat()
    found = {}
    for query in QUERIES:
        results = yt('search', {'part':'snippet', 'type':'video', 'q':query, 'maxResults':5, 'order':'relevance'})
        for item in results.get('items', []):
            found[item['id']['videoId']] = query
    if not found:
        raise RuntimeError('Nenhum vídeo retornado pela API')
    details = yt('videos', {'part':'snippet,statistics,contentDetails', 'id':','.join(found)})['items']
    channel_ids = sorted({v['snippet']['channelId'] for v in details})
    channels_raw = yt('channels', {'part':'snippet,statistics,contentDetails', 'id':','.join(channel_ids)})['items']
    channels = []
    channel_history = []
    for c in channels_raw:
        stats = c.get('statistics', {})
        count = None if stats.get('hiddenSubscriberCount') else int(stats.get('subscriberCount', 0))
        channels.append({'id':c['id'], 'name':c['snippet']['title'], 'url':'https://www.youtube.com/channel/'+c['id'],
                         'created_at_youtube':c['snippet'].get('publishedAt'), 'subscriber_count':count,
                         'video_count':int(stats.get('videoCount', 0)), 'collected_at':now.isoformat()})
        channel_history.append({'channel_id':c['id'], 'collected_date':today, 'subscriber_count':count,
                                'video_count':int(stats.get('videoCount', 0))})
    videos = []
    video_history = []
    for v in details:
        views = int(v.get('statistics', {}).get('viewCount', 0))
        likes = int(v.get('statistics', {}).get('likeCount', 0)) if 'likeCount' in v.get('statistics', {}) else None
        videos.append({'id':v['id'], 'channel_id':v['snippet']['channelId'], 'title':v['snippet']['title'],
                       'url':'https://www.youtube.com/watch?v='+v['id'], 'published_at':v['snippet']['publishedAt'],
                       'view_count':views, 'like_count':likes, 'niche':found[v['id']], 'collected_at':now.isoformat()})
        video_history.append({'video_id':v['id'], 'collected_date':today, 'view_count':views, 'like_count':likes})
    upsert('channels', channels)
    upsert('videos', videos)
    upsert('channel_metrics_history', channel_history, 'channel_id,collected_date')
    upsert('video_metrics_history', video_history, 'video_id,collected_date')
    print(f'Coleta concluída: {len(channels)} canais e {len(videos)} vídeos.')

if __name__ == '__main__':
    main()
