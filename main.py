import os
import re
import time
import json
import random
import asyncio
import datetime
import xml.etree.ElementTree as ET
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

# J-STAGE収録の日本史・歴史学主要学術誌（15誌）
# require_jp=True は西洋史・東洋史等も含むため「日本」で絞り込む
JOURNALS = [
    {"code": "nihonshikenkyu", "name": "日本史研究", "require_jp": False},
    {"code": "kotsushi", "name": "交通史研究", "require_jp": False},
    {"code": "nihonkokogaku1994", "name": "日本考古学", "require_jp": False},
    {"code": "chiikishikenkyu", "name": "地域史研究", "require_jp": False},
    {"code": "nihonminzokugaku", "name": "日本民俗学", "require_jp": False},
    {"code": "shigaku", "name": "史学雑誌", "require_jp": True},
    {"code": "jinreki", "name": "人民の歴史学", "require_jp": True},
    {"code": "histgeo", "name": "歴史地理学", "require_jp": True},
    {"code": "sehs", "name": "社会経済史学", "require_jp": True},
    {"code": "rekishitokeizai", "name": "歴史と経済", "require_jp": True},
    {"code": "bhsj", "name": "経営史学", "require_jp": True},
    {"code": "jalha", "name": "法制史研究", "require_jp": True},
    {"code": "jsahj", "name": "建築史学", "require_jp": True},
    {"code": "jshm", "name": "日本医史学雑誌", "require_jp": True},
    {"code": "jhsj", "name": "科学史研究", "require_jp": True},
]

# 書評・学会報告・目次・回顧と展望などを除外するNGワード
EXCLUDE_WORDS = [
    "書評", "新刊紹介", "紹介", "彙報", "例会", "大会", "シンポジウム",
    "追悼", "目録", "総目次", "目次", "表紙", "CONTENTS", "編集後記",
    "学会動向", "文献目録", "回顧と展望", "学界消息", "受贈図書", "奥付"
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; DailyHistoryPodcast/1.0)"
}


def load_history():
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    return []


def save_history(history):
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def is_valid_paper_title(title):
    """書評・目次・学会報告などを除外する"""
    if len(title) < 6:
        return False
    for ng in EXCLUDE_WORDS:
        if ng in title:
            return False
    return True


def fetch_random_paper(history):
    """日本史の主要学術誌をランダムに選び、そこから未読のPDF論文を1本取得"""
    journals = JOURNALS.copy()
    random.shuffle(journals)
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "prism": "http://prismstandard.org/namespaces/basic/2.0/",
    }

    for journal in journals:
        api_url = "https://api.jstage.jst.go.jp/searchapi/do"

        # 毎回同じ最新号ばかりにならないよう、開始位置をランダムにする（ヒットしなければ1から再検索）
        start_positions = [random.randint(1, 200), 1]

        for start_pos in start_positions:
            params = {
                "service": "3",
                "cdjournal": journal["code"],
                "count": "50",
                "start": str(start_pos),
            }
            if journal["require_jp"]:
                params["text"] = "日本"

            try:
                res = requests.get(api_url, params=params, headers=HEADERS, timeout=20)
                if res.status_code != 200:
                    continue
                root = ET.fromstring(res.content)
            except Exception:
                continue

            entries = root.findall("atom:entry", ns)
            if not entries:
                continue

            random.shuffle(entries)

            for entry in entries:
                paper_id_el = entry.find("atom:id", ns)
                title_el = entry.find("atom:title", ns)
                link_el = entry.find("atom:link", ns)
                if paper_id_el is None or title_el is None or link_el is None:
                    continue

                paper_id = paper_id_el.text.strip()
                title = title_el.text.strip()

                if paper_id in history or not is_valid_paper_title(title):
                    continue

                article_url = link_el.attrib.get("href", "")
                if "/_article" not in article_url:
                    continue

                # J-STAGEの論文ページURLをPDF直リンクに変換
                pdf_url = re.sub(r"/_article.*", "/_pdf/-char/ja", article_url)

                # 著者名を取得
                authors = [
                    a.find("atom:name", ns).text.strip()
                    for a in entry.findall("atom:author", ns)
                    if a.find("atom:name", ns) is not None and a.find("atom:name", ns).text
                ]
                author_str = ", ".join(authors) if authors else "著者不明"

                # 出版年を取得
                pub_year = "出版年不明"
                pub_year_el = entry.find("prism:publicationDate", ns)
                if pub_year_el is not None and pub_year_el.text:
                    pub_year = pub_year_el.text.strip()[:4] + "年"
                else:
                    for elem in entry:
                        if elem.tag.endswith("pubyear") and elem.text:
                            pub_year = elem.text.strip() + "年"
                            break

                # PDFをダウンロードして本物の論文PDFか確認（150KB以上）
                try:
                    pdf_res = requests.get(pdf_url, headers=HEADERS, timeout=30, allow_redirects=True)
                    if (
                        pdf_res.status_code == 200
                        and len(pdf_res.content) > 150_000
                        and pdf_res.content[:4] == b"%PDF"
                    ):
                        pdf_path = Path("temp_paper.pdf")
                        pdf_path.write_bytes(pdf_res.content)
                        return {
                            "id": paper_id,
                            "title": title,
                            "author": author_str,
                            "journal": journal["name"],
                            "pub_year": pub_year,
                            "url": article_url,
                            "pdf_path": pdf_path,
                        }
                except Exception:
                    continue

    raise RuntimeError("取得可能なPDF付き論文が見つかりませんでした。")


def generate_script(paper):
    """Gemini API（無料枠）にPDFを直接渡して、論証重視の約30分解説台本を生成"""
    client = genai.Client(api_key=GEMINI_API_KEY)
    uploaded_file = client.files.upload(file=str(paper["pdf_path"]))

    prompt = f"""
あなたは日本史学を専門とする学術解説者です。
添付の日本史学術論文を、耳だけで聞いて内容を深く正確に理解できるように、約30分間（8,500〜9,500文字）の解説音声台本を作成してください。

【書誌情報】
論文名：{paper['title']}
著者：{paper['author']}
掲載雑誌：{paper['journal']}
出版年：{paper['pub_year']}

【構成と内容の厳守事項】
1. 導入（冗長な挨拶・雑談は一切不要）：
   - 「おはようございます」「今日も聞いていただきありがとうございます」などの挨拶や雑談は一切入れず、いきなり本題に入ること。
   - 最初に必ず「論文名」「著者名」「掲載雑誌名」「出版年」を明確に述べること。
   - 添付PDFの冒頭・末尾・脚注などに著者の所属機関や肩書（大学名・職位など）が記載されていれば、必ずそれも併せて紹介すること（記載がない場合は無理に推測しないこと）。
2. 研究の背景と問題設定（約1,500文字）：
   - 先行研究で何が通説とされており、そこにどのような限界や未解明の点があるのかを具体的に整理する。
   - 本論文が立てた問い（リサーチ・クエスチョン）を明確に示す。
3. 具体的な論証プロセス（約6,000文字・最重要パート）：
   - 結論だけを抽象的にまとめるのではなく、「著者がどのような史料（古文書・日記・帳簿・考古資料など）を取り上げ、その記述やデータをどう読み解き、どのような論理のステップを踏んで主張を裏付けているのか」を、章立てに沿って具体的・緻密に解説すること。
   - 史料の引用や具体的な事例・年代・地名・人物名を省かず、耳で聞いて論理の筋道が追えるように丁寧に説明すること。
4. 結論と学術的意義（約1,500文字）：
   - 論証から導かれた結論と、それが従来の日本史像や先行研究をどう書き換えるのかをまとめる。
   - 締めの挨拶も不要。解説のまとめで簡潔に終えること。

【音声読み上げ（TTS）向けの厳守事項】
- Markdown記号（#、*、-、`、箇条書き記号など）や見出し番号の記号は一切使わないこと。
- 話し言葉のプレーンテキストのみで出力すること。
- 難読漢字・古文書用語・歴史用語には、自然な文脈の中で読み方や簡潔な意味の補足を添えること。
"""

    models = ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.6-flash"]
    last_error = None
    for model_name in models:
        for attempt in range(2):
            try:
                print(f"Trying model: {model_name} (attempt {attempt + 1})")
                response = client.models.generate_content(
                    model=model_name,
                    contents=[uploaded_file, prompt],
                )
                return response.text.strip()
            except Exception as e:
                last_error = e
                print(f"Failed with {model_name}: {e}")
                time.sleep(10)
    raise last_error


async def text_to_speech(text, output_mp3):
    """edge-ttsで日本語ニューラル音声（完全無料）を生成"""
    # 女性声: ja-JP-NanamiNeural / 男性声: ja-JP-KeitaNeural
    communicate = edge_tts.Communicate(text, voice="ja-JP-NanamiNeural", rate="+0%")
    await communicate.save(str(output_mp3))


def cleanup_old_episodes():
    """直近MAX_KEEP_DAYS件のみ残して古いMP3とメタデータを削除"""
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
        fe.description(
            f"著者：{meta['author']}\n"
            f"雑誌：{meta.get('journal', '不明')}（{meta.get('pub_year', '不明')}）\n"
            f"元論文：{meta['url']}"
        )
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
    print(f"Selected: [{paper['journal']} ({paper['pub_year']})] {paper['title']}")

    script = generate_script(paper)
    print(f"Script generated: {len(script)} chars")

    jst = datetime.timezone(datetime.timedelta(hours=9))
    now = datetime.datetime.now(jst)
    date_str = now.strftime("%Y-%m-%d")
    file_stem = now.strftime("%Y-%m-%d-%H%M%S")

    mp3_path = EPISODES_DIR / f"{file_stem}.mp3"
    asyncio.run(text_to_speech(script, mp3_path))

    # エピソード情報を保存
    meta = {
        "id": paper["id"],
        "date": date_str,
        "pub_date": now.isoformat(),
        "title": paper["title"],
        "author": paper["author"],
        "journal": paper["journal"],
        "pub_year": paper["pub_year"],
        "url": paper["url"],
    }
    (EPISODES_DIR / f"{file_stem}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    history.append(paper["id"])
    save_history(history)

    cleanup_old_episodes()
    build_rss_feed()
    print("Done!")


if __name__ == "__main__":
    main()
