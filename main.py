import os
import json
import random
import asyncio
import datetime
from pathlib import Path
import requests
import edge_tts
from google import genai
from feedgen.feed import FeedGenerator

# --- 設定 ---
GITHUB_USERNAME = os.environ["GITHUB_USERNAME"]
REPO_NAME = os.environ["REPO_NAME"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
BASE_URL = f"https://{GITHUB_USERNAME}.github.io/{REPO_NAME}"

DOCS_DIR = Path("docs")
EPISODES_DIR = DOCS_DIR / "episodes"
HISTORY_FILE = Path("history.json")
MAX_KEEP_DAYS = 7

# ランダム選書用の日本史キーワード
KEYWORDS = [
    "縄文時代", "弥生時代", "古墳時代", "律令制", "平安時代", "荘園",
    "鎌倉幕府", "室町時代", "戦国大名", "織豊政権", "幕藩体制", "江戸時代 文化",
    "蘭学", "幕末", "明治維新", "自由民権運動", "大正デモクラシー", "日本近現代史"
]

def load_history():
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    return []

def save_history(history):
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

def extract_urls(field):
    """辞書・リスト・文字列のどの形式でも安全にURL一覧を取り出す"""
    urls = []
    if isinstance(field, str):
        urls.append(field)
    elif isinstance(field, dict):
        if "@id" in field:
            urls.append(field["@id"])
    elif isinstance(field, list):
        for entry in field:
            urls.extend(extract_urls(entry))
    return urls

def fetch_random_paper(history):
    """CiNii Research APIから本文PDF付きの日本史論文をランダム取得"""
    random.shuffle(KEYWORDS)
    for kw in KEYWORDS:
        url = "https://cir.nii.ac.jp/opensearch/articles"
        params = {
            "q": f"日本史 {kw}",
            "hasLinkToFullText": "true",
            "format": "json",
            "count": 30,
        }
        res = requests.get(url, params=params, timeout=20)
        if res.status_code != 200:
            continue

        items = res.json().get("items", [])
        random.shuffle(items)

        for item in items:
            paper_id = item.get("@id")
            if not paper_id or paper_id in history:
                continue

            # link と rdfs:seeAlso の両方からPDFリンクを探す
            candidate_urls = (
                extract_urls(item.get("link"))
                + extract_urls(item.get("rdfs:seeAlso"))
            )
            pdf_url = None
            for href in candidate_urls:
                if ".pdf" in href.lower() or "/_pdf" in href.lower():
                    pdf_url = href
                    break

            if not pdf_url:
                continue

            # PDFをダウンロードして中身が本物のPDFか確認
            try:
                pdf_res = requests.get(pdf_url, timeout=30)
                if (
                    pdf_res.status_code == 200
                    and len(pdf_res.content) > 50_000
                    and pdf_res.content[:4] == b"%PDF"
                ):
                    pdf_path = Path("temp_paper.pdf")
                    pdf_path.write_bytes(pdf_res.content)
                    creators = item.get("dc:creator", ["著者不明"])
                    if isinstance(creators, str):
                        creators = [creators]
                    return {
                        "id": paper_id,
                        "title": item.get("title", "無題の日本史論文"),
                        "author": ", ".join(creators),
                        "url": paper_id,
                        "keyword": kw,
                        "pdf_path": pdf_path,
                    }
            except Exception:
                continue

    raise RuntimeError("取得可能なPDF付き論文が見つかりませんでした。")

def generate_script(paper):
    """Gemini API（無料枠）にPDFを直接渡して約9,000文字の解説台本を生成"""
    client = genai.Client(api_key=GEMINI_API_KEY)
    uploaded_file = client.files.upload(file=str(paper["pdf_path"]))

    prompt = f"""
あなたは歴史系ポッドキャストの優秀なパーソナリティです。
添付の日本史学術論文を、朝ごはんを作りながら耳だけで聞いて楽しめるように、約30分間（8,500〜9,500文字）の解説ラジオ台本にしてください。

【論文情報】
タイトル：{paper['title']}
著者：{paper['author']}

【構成の目安】
1. オープニング（約500文字）：朝の挨拶、論文のテーマと「何が面白いのか」の導入
2. 時代背景と先行研究（約1,500文字）：これまでの通説と、著者が抱いた疑問
3. 本論の深掘り（約5,000文字）：論文の主張と史料の読み解きを3〜4章に分けて丁寧に解説
4. 結論と歴史的意義（約1,500文字）：この研究で歴史の見方がどう変わるか
5. エンディング（約500文字）：要点の振り返りと締めの挨拶

【厳守事項】
- 音声読み上げソフト（TTS）にそのまま渡すため、Markdown記号（#、*、-、` など）や見出し記号は一切使わないこと。
- 話し言葉のプレーンテキストのみで出力すること。
- 難読漢字や専門用語には、自然な会話の中で読み方や簡単な補足を入れること。
"""
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[uploaded_file, prompt],
    )
    return response.text.strip()

async def text_to_speech(text, output_mp3):
    """edge-ttsで日本語ニューラル音声（完全無料）を生成"""
    # 女性声: ja-JP-NanamiNeural / 男性声: ja-JP-KeitaNeural
    communicate = edge_tts.Communicate(text, voice="ja-JP-NanamiNeural", rate="+0%")
    await communicate.save(str(output_mp3))

def cleanup_old_episodes():
    """直近MAX_KEEP_DAYS日分のみ残して古いMP3とメタデータを削除"""
    files = sorted(EPISODES_DIR.glob("*.json"), reverse=True)
    for old_meta in files[MAX_KEEP_DAYS:]:
        mp3_file = old_meta.with_suffix(".mp3")
        if mp3_file.exists():
            mp3_file.unlink()
        old_meta.unlink()

def build_rss_feed():
    """Apple Podcast用のfeed.xmlを生成"""
    fg = FeedGenerator()
    fg.load_extension("podcast")
    fg.title("毎朝の日本史論文ラジオ")
    fg.link(href=BASE_URL, rel="alternate")
    fg.description("公開されている日本史の学術論文を毎朝ランダムに30分解説するプライベート番組")
    fg.language("ja")
    fg.podcast.itunes_category("History")

    for meta_file in sorted(EPISODES_DIR.glob("*.json"), reverse=True):
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        mp3_path = meta_file.with_suffix(".mp3")
        if not mp3_path.exists():
            continue

        fe = fg.add_entry()
        fe.id(meta["id"])
        fe.title(f"{meta['date']} {meta['title']}")
        fe.description(f"著者：{meta['author']}\nテーマ：{meta['keyword']}\n元論文：{meta['url']}")
        fe.pubDate(meta["pub_date"])
        fe.enclosure(
            f"{BASE_URL}/episodes/{mp3_path.name}",
            str(mp3_path.stat().st_size),
            "audio/mpeg",
        )

    fg.rss_file(str(DOCS_DIR / "feed.xml"))

def main():
    EPISODES_DIR.mkdir(parents=True, exist_ok=True)
    history = load_history()

    paper = fetch_random_paper(history)
    print(f"Selected: {paper['title']}")

    script = generate_script(paper)
    print(f"Script generated: {len(script)} chars")

    jst = datetime.timezone(datetime.timedelta(hours=9))
    now = datetime.datetime.now(jst)
    date_str = now.strftime("%Y-%m-%d")

    mp3_path = EPISODES_DIR / f"{date_str}.mp3"
    asyncio.run(text_to_speech(script, mp3_path))

    # エピソード情報を保存
    meta = {
        "id": paper["id"],
        "date": date_str,
        "pub_date": now.isoformat(),
        "title": paper["title"],
        "author": paper["author"],
        "keyword": paper["keyword"],
        "url": paper["url"],
    }
    (EPISODES_DIR / f"{date_str}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    history.append(paper["id"])
    save_history(history)

    cleanup_old_episodes()
    build_rss_feed()
    print("Done!")

if __name__ == "__main__":
    main()
