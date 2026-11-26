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

# ランダム選書用の日本史キーワード
KEYWORDS = [
    "縄文時代", "弥生時代", "古墳時代", "律令制", "平安時代", "荘園",
    "鎌倉幕府", "室町時代", "戦国大名", "織豊政権", "幕藩体制", "江戸時代",
    "蘭学", "幕末", "明治維新", "自由民権運動", "大正デモクラシー", "日本近現代史"
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


def fetch_random_paper(history):
    """J-STAGE公式APIから本文PDF付きの日本史論文をランダム取得"""
    random.shuffle(KEYWORDS)
    ns = {"atom": "http://www.w3.org/2005/Atom"}

    for kw in KEYWORDS:
        api_url = "https://api.jstage.jst.go.jp/searchapi/do"
        params = {
            "service": "3",
            "text": f"日本史 {kw}",
            "count": "30",
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
            if paper_id in history:
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

            # PDFをダウンロードして本物のPDFか確認
            try:
                pdf_res = requests.get(pdf_url, headers=HEADERS, timeout=30, allow_redirects=True)
                if (
                    pdf_res.status_code == 200
                    and len(pdf_res.content) > 50_000
                    and pdf_res.content[:4] == b"%PDF"
                ):
                    pdf_path = Path("temp_paper.pdf")
                    pdf_path.write_bytes(pdf_res.content)
                    return {
                        "id": paper_id,
                        "title": title_el.text.strip(),
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
    uploaded_
