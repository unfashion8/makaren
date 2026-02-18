# -*- coding: utf-8 -*-
"""
Yahoo!オークション UNFASHION 出品者ページから商品一覧を取得し、
data/unfashion_products.json に保存するスクリプト。

使い方（プロジェクトルートで）:
  pip install requests beautifulsoup4
  python scripts/fetch_yahoo_auction_listings.py

注意: Yahoo!オークションの利用規約を確認の上、自己責任で実行してください。
      過度なアクセスは避け、実行間隔をあけてください。
"""
import json
import re
import time
import sys
from pathlib import Path

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("必要なパッケージをインストールしてください: pip install requests beautifulsoup4")
    sys.exit(1)

SELLER_ID = "4XQdPCTXHMTSxfGS6kcu2ab1B3GFN"
BASE_URL = "https://auctions.yahoo.co.jp/seller/" + SELLER_ID
PER_PAGE = 50
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "unfashion_products.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en;q=0.9",
}


def fetch_page(b: int) -> str:
    """1ページ分のHTMLを取得。b=1,51,101,..."""
    url = f"{BASE_URL}?fixed=0&b={b}&n={PER_PAGE}&select=23&mode=3"
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text


def parse_items(html: str) -> list[dict]:
    """HTMLから商品リストをパースする。"""
    soup = BeautifulSoup(html, "html.parser")
    items = []

    # 商品リンク (Yahooオークションの商品URL形式)
    for a in soup.select('a[href*="/jp/show/auc/"]'):
        href = a.get("href") or ""
        if "javascript:" in href or not href.strip():
            continue
        if not href.startswith("http"):
            href = "https://auctions.yahoo.co.jp" + href.split("?")[0] if href.startswith("/") else "https://auctions.yahoo.co.jp" + href
        # 同じ商品の重複を避けるため、auction ID をキーにする
        m = re.search(r"/auc/([a-zA-Z0-9]+)", href)
        auc_id = m.group(1) if m else None
        if not auc_id:
            continue

        # タイトル: リンクテキストまたは親要素
        title = (a.get_text(strip=True) or "").strip()
        if not title or len(title) < 2:
            parent = a.find_parent(["div", "li", "section"])
            if parent:
                title = (parent.get_text(separator=" ", strip=True) or "").strip()[:200]
        title = title[:200] if title else "（タイトルなし）"

        # 画像: 同じカード内の img
        img_url = None
        card = a.find_parent(["li", "div", "article"])
        if card:
            img = card.select_one("img[src*='yahoo']") or card.select_one("img")
            if img and img.get("src"):
                img_url = img.get("src", "").strip()
                if img_url.startswith("//"):
                    img_url = "https:" + img_url

        # 価格: 同じカード内の数値
        price = None
        price_text = None
        if card:
            text = card.get_text()
            yen = re.search(r"([¥￥])\s*([0-9,]+)", text)
            if yen:
                price_text = "¥" + yen.group(2).replace(",", "")
                try:
                    price = int(yen.group(2).replace(",", ""))
                except ValueError:
                    pass

        items.append({
            "id": auc_id,
            "title": title,
            "url": href.split("?")[0] if "?" in href else href,
            "image_url": img_url,
            "price": price,
            "price_label": price_text,
            "category": None,
        })

    # 重複除去（id で）
    seen = set()
    unique = []
    for x in items:
        if x["id"] not in seen:
            seen.add(x["id"])
            unique.append(x)
    return unique


def main():
    all_items = []
    page = 1
    start = 1

    print("UNFASHION 出品一覧を取得しています...")
    while True:
        try:
            html = fetch_page(start)
            batch = parse_items(html)
            if not batch:
                # 1ページ目で取れない場合は終了（JS描画の可能性）
                if page == 1:
                    print("商品リストを取得できませんでした。ページがJavaScriptで描画されている可能性があります。")
                    print("ブラウザで該当ページを開き、開発者ツールでHTML構造を確認するか、")
                    print("data/unfashion_products.json を手動で編集してください。")
                break
                break
            all_items.extend(batch)
            print(f"  ページ {page}: {len(batch)} 件 (累計 {len(all_items)} 件)")
            if len(batch) < PER_PAGE:
                break
            start += PER_PAGE
            page += 1
            time.sleep(1.5)  # サーバー負荷軽減
        except requests.RequestException as e:
            print(f"エラー: {e}")
            break

    data = {
        "seller_name": "UNFASHION",
        "seller_url": BASE_URL,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S+09:00", time.localtime()),
        "total": len(all_items),
        "items": all_items,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"保存しました: {OUTPUT_PATH} ({len(all_items)} 件)")


if __name__ == "__main__":
    main()
