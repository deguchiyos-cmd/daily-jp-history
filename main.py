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

# 日本史固有の学術キーワード（約250語・他分野と被らない用語のみ厳選）
KEYWORDS = [
    # 原始・古代
    "縄文時代", "縄文土器", "弥生時代", "弥生土器", "邪馬台国", "前方後円墳", "埴輪", "ヤマト王権",
    "氏姓制度", "部民制", "屯倉", "飛鳥時代", "飛鳥京", "大化改新", "壬申の乱", "藤原京",
    "律令国家", "大宝律令", "養老律令", "奈良時代", "平城京", "長岡京", "平安時代", "平安京",
    "国司", "郡司", "班田収授", "口分田", "墾田永年私財法", "租庸調", "出挙", "太政官",
    "摂関政治", "院政", "受領", "遣隋使", "遣唐使", "渤海使", "大宰府", "防人",
    "蝦夷", "多賀城", "国分寺", "東大寺", "正倉院", "神仏習合", "古事記", "日本書紀",
    "風土記", "万葉集", "延喜式", "六国史", "白鳳文化", "天平文化", "国風文化",
    "承平天慶の乱", "前九年の役", "後三年の役", "奥州藤原氏", "平泉",

    # 中世
    "荘園公領制", "寄進地系荘園", "国衙領", "平氏政権", "源平合戦", "治承寿永の乱", "鎌倉幕府", "鎌倉時代",
    "御家人", "守護", "地頭", "執権政治", "御成敗式目", "承久の乱", "元寇", "蒙古襲来",
    "悪党", "永仁の徳政令", "建武の新政", "南北朝時代", "室町幕府", "室町時代", "守護大名", "守護請",
    "半済令", "国人一揆", "惣村", "土一揆", "正長の土一揆", "山城国一揆", "一向一揆", "法華一揆",
    "応仁の乱", "戦国大名", "戦国時代", "分国法", "織豊政権", "楽市楽座", "刀狩",
    "延暦寺", "興福寺", "高野山", "本願寺", "鎌倉仏教", "五山文学", "日宋貿易", "日明貿易",
    "勘合貿易", "倭寇", "琉球王国", "花押", "中世村落", "北条氏", "足利氏", "六波羅探題",
    "鎌倉公方", "関東管領", "下剋上", "検断", "年貢", "撰銭令", "馬借", "問丸", "吾妻鏡",

    # 近世
    "幕藩制", "幕藩体制", "太閤検地", "兵農分離", "石高制", "江戸幕府", "江戸時代", "武家諸法度",
    "禁中並公家諸法度", "参勤交代", "改易", "旗本", "藩政改革", "享保の改革", "寛政の改革", "天保の改革",
    "田沼時代", "近世村落", "村請制", "五人組", "名主", "庄屋", "本百姓", "水呑百姓",
    "村方騒動", "百姓一揆", "打ちこわし", "世直し一揆", "ええじゃないか", "在郷町", "三都", "町人文化",
    "株仲間", "両替商", "蔵屋敷", "札差", "菱垣廻船", "樽廻船", "北前船", "五街道",
    "助郷", "関所", "長崎貿易", "出島", "唐人屋敷", "朝鮮通信使", "琉球使節", "蝦夷地",
    "アイヌ", "松前藩", "寺請制度", "宗門改帳", "キリシタン", "島原の乱", "国学", "蘭学",
    "浮世絵", "尊王攘夷", "公武合体", "倒幕運動", "戊辰戦争", "大政奉還", "王政復古",
    "生類憐みの令", "元禄文化", "化政文化", "寺子屋", "藩校", "往来物", "伊勢参り",

    # 近現代
    "ペリー来航", "日米和親条約", "日米修好通商条約", "安政の大獄", "桜田門外の変", "薩長同盟",
    "明治維新", "明治時代", "五箇条の御誓文", "版籍奉還", "廃藩置県", "四民平等", "秩禄処分", "地租改正",
    "徴兵令", "殖産興業", "富岡製糸場", "文明開化", "岩倉使節団", "征韓論", "西南戦争", "自由民権運動",
    "大日本帝国憲法", "帝国議会", "教育勅語", "市制町村制", "府県制", "条約改正", "日清戦争", "日露戦争",
    "韓国併合", "大正時代", "大正デモクラシー", "護憲運動", "米騒動", "普通選挙法", "治安維持法", "地方改良運動",
    "全国水平社", "昭和恐慌", "満洲事変", "五一五事件", "二二六事件", "日中戦争", "国家総動員法", "大政翼賛会",
    "学徒出陣", "ポツダム宣言", "日本国憲法", "GHQ", "財閥解体", "農地改革",
    "サンフランシスコ平和条約", "日米安全保障条約", "高度経済成長", "昭和戦前期", "戦後日本"
]

# 書評・学会報告・学校教育系を除外するNGワード
EXCLUDE_WORDS = [
    "書評", "新刊紹介", "紹介", "彙報", "例会", "大会", "シンポジウム",
    "追悼", "目録", "総目次", "編集後記", "学会動向", "文献目録",
    "中学校", "高等学校", "高校", "小学校", "社会科", "授業", "指導", "教科書", "入試"
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
    """書評・紹介・教育実践などを除外する"""
    for ng in EXCLUDE_WORDS:
        if ng in title:
            return False
    return True


def fetch_random_paper(history):
    """J-STAGE公式APIから本文PDF付きの日本史論文をランダム取得"""
    random.shuffle(KEYWORDS)
    ns = {"atom": "http://www.w3.org/2005/Atom"}

    for kw in KEYWORDS:
        api_url = "https://api.jstage.jst.go.jp/searchapi/do"
        params = {
            "service": "3",
            "text": f"日本史 {kw}",
            "count": "50",
        }
        try:
            res = requests.get(api_url, params=params, headers=HEADERS, timeout=20)
            if res.status_code != 200:
                continue
            root = ET.fromstring(res.content)
        except Exception:
            continue

        entries = root.findall("atom:entry", ns)
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

            # PDFをダウンロードして本物の論文PDFか確認（120KB以上）
            try:
                pdf_res = requests.get(pdf_url, headers=HEADERS, timeout=30, allow_redirects=True)
                if (
                    pdf_res.status_code == 200
                    and len(pdf_res.content) > 120_000
                    and pdf_res.content[:4] == b"%PDF"
                ):
                    pdf_path = Path("temp_paper.pdf")
                    pdf_path.write_bytes(pdf_res.content)
                    return {
                        "id": paper_id,
                        "title": title,
                        "author": author_str,
                        "url": article_url,
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
