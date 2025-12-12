"""
Matrixify 向けに yumejin の商品データを変換するスクリプト。

- products/ 配下の Shift_JIS CSV を読み込み、UTF-8 で Matrixify が受け取れる形式の CSV を生成する。
- 現状はバリアント 1 つの商品だけを想定し、価格・カテゴリ・画像の最低限の情報を出力する。
"""
from __future__ import annotations

import csv
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# W2 repeat 画像ルールに合わせたベース URL
BASE_IMAGE_URL = "https://www.yumejin.jp/Contents/ProductImages/0/"
SUB_IMAGE_URL = "https://www.yumejin.jp/Contents/ProductSubImages/0/"
IMAGE_EXTENSIONS = [".jpg"]
IMAGE_SUFFIXES = ["_L", "_LL", "_M", "_S"]
MAX_WORKERS = 16
REQUEST_TIMEOUT = 1.5

ROOT_DIR = Path(__file__).resolve().parent.parent
INPUT_DIR = ROOT_DIR / "products"
OUTPUT_DIR = ROOT_DIR / "output"

PRODUCT_FILE = INPUT_DIR / "Product20251211.csv"
STOCK_FILE = INPUT_DIR / "ProductStock20251211.csv"
CATEGORY_FILE = INPUT_DIR / "ProductCategory20251211.csv"


@dataclass
class Category:
    category_id: str
    parent_category_id: str
    name: str


@dataclass
class Product:
    product_id: str
    name: str
    body_html: str
    display_price: Optional[Decimal]
    display_special_price: Optional[Decimal]
    category_ids: List[str]
    image_head: str


logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(message)s")


def decode_shift_jis_lines(path: Path) -> List[str]:
    """Shift_JIS で 1 行ずつデコードし、失敗した行をログに出してスキップする。"""
    lines: List[str] = []
    with path.open("rb") as f:
        for index, raw_line in enumerate(f, start=1):
            try:
                lines.append(raw_line.decode("shift_jis"))
            except UnicodeDecodeError as exc:
                logging.warning("Shift_JIS デコードエラー: %s (line %d) %s", path.name, index, exc)
    return lines


def read_csv_dicts(path: Path) -> List[Dict[str, str]]:
    decoded_lines = decode_shift_jis_lines(path)
    reader = csv.DictReader(decoded_lines)
    return list(reader)


def parse_decimal(value: str) -> Optional[Decimal]:
    value = value.strip()
    value = value.replace(",", "")
    if not value:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        logging.warning("数値に変換できない値を検出しました: %s", value)
        return None


def parse_int(value: str) -> int:
    value = value.strip()
    if not value:
        return 0
    try:
        return int(value)
    except ValueError:
        logging.warning("整数に変換できない値を検出しました: %s", value)
        return 0


def load_categories() -> Dict[str, Category]:
    categories: Dict[str, Category] = {}
    for row in read_csv_dicts(CATEGORY_FILE):
        category_id = row.get("category_id", "").strip()
        if not category_id:
            continue
        categories[category_id] = Category(
            category_id=category_id,
            parent_category_id=row.get("parent_category_id", "").strip(),
            name=row.get("name", "").strip(),
        )
    return categories


def build_category_paths(categories: Dict[str, Category]) -> Dict[str, str]:
    """カテゴリ ID からルートまでの名称を `/` で連結したパスを作成する。"""
    cache: Dict[str, str] = {}

    def resolve_path(category_id: str, trail: Optional[Sequence[str]] = None) -> str:
        if category_id in cache:
            return cache[category_id]
        trail = list(trail or []) + [category_id]
        category = categories.get(category_id)
        if not category:
            logging.warning("カテゴリ ID %s が見つかりません", category_id)
            cache[category_id] = ""
            return ""
        if category.parent_category_id.lower() == "root" or not category.parent_category_id:
            path = category.name
        else:
            if category.parent_category_id in trail:
                logging.warning("カテゴリの循環参照を検出しました: %s", " -> ".join(trail))
                path = category.name
            else:
                parent_path = resolve_path(category.parent_category_id, trail)
                path = f"{parent_path}/{category.name}" if parent_path else category.name
        cache[category_id] = path
        return path

    for cat_id in categories:
        resolve_path(cat_id)
    return cache


def build_body_html(row: Dict[str, str]) -> str:
    """商品説明に利用できそうなカラムを HTML で簡易結合する。"""
    parts: List[str] = []
    for key in ["catchcopy", "outline", "desc_detail1", "desc_detail2", "desc_detail3", "desc_detail4"]:
        value = (row.get(key) or "").strip()
        if value:
            parts.append(f"<p>{value}</p>")
    return "".join(parts)


def load_products() -> List[Product]:
    products: List[Product] = []
    for row in read_csv_dicts(PRODUCT_FILE):
        product_id = (row.get("product_id") or "").strip()
        if not product_id:
            continue
        products.append(
            Product(
                product_id=product_id,
                name=(row.get("name") or "").strip(),
                body_html=build_body_html(row),
                display_price=parse_decimal(row.get("display_price", "")),
                display_special_price=parse_decimal(row.get("display_special_price", "")),
                category_ids=[(row.get(f"category_id{i}") or "").strip() for i in range(1, 6)],
                image_head=(row.get("image_head") or "").strip(),
            )
        )
    return products


def load_stocks() -> Dict[str, int]:
    stocks: Dict[str, int] = {}
    for row in read_csv_dicts(STOCK_FILE):
        product_id = (row.get("product_id") or "").strip()
        if not product_id:
            continue
        stock_value = parse_int(row.get("stock", "0"))
        stocks[product_id] = stocks.get(product_id, 0) + stock_value
    return stocks


def select_prices(product: Product) -> tuple[str, str]:
    """価格と比較対象価格を Matrixify 用に決定する。

    display_special_price が存在する場合はセール価格として Price に設定し、
    display_price との比較で値引きがあるときだけ Compare at Price を埋める。
    display_special_price が無い場合は display_price をそのまま Price に入れる。
    """

    price = product.display_price
    special = product.display_special_price

    if special is not None:
        compare_at = price if price is not None and special < price else None
        return (f"{special}", f"{compare_at}" if compare_at is not None else "")

    if price is not None:
        return (f"{price}", "")

    return ("", "")


def build_product_category(product: Product, category_paths: Dict[str, str]) -> str:
    paths: List[str] = []
    for category_id in product.category_ids:
        if not category_id:
            continue
        path = category_paths.get(category_id, "")
        if path:
            paths.append(path)
    return " | ".join(dict.fromkeys(paths))


def generate_image_candidates(image_head: str) -> List[str]:
    if not image_head:
        return []

    has_suffix = any(image_head.endswith(suffix) for suffix in IMAGE_SUFFIXES)
    heads = [image_head] if has_suffix else [f"{image_head}{suffix}" for suffix in IMAGE_SUFFIXES]

    candidates: List[str] = []
    for head in heads:
        for ext in IMAGE_EXTENSIONS:
            candidates.append(f"{head}{ext}")
    return candidates


def url_exists(url: str, cache: Dict[str, bool], lock: threading.Lock) -> bool:
    with lock:
        if url in cache:
            return cache[url]

    exists = False
    range_request = Request(url, headers={"Range": "bytes=0-0"})
    try:
        with urlopen(range_request, timeout=REQUEST_TIMEOUT) as response:
            exists = response.status in (200, 206, 304)
    except HTTPError:
        pass
    except URLError:
        pass

    with lock:
        cache[url] = exists
    return exists


def find_first_existing(candidates: List[str], cache: Dict[str, bool], lock: threading.Lock) -> Tuple[str, List[str]]:
    tried_urls: List[str] = []
    for url in candidates:
        tried_urls.append(url)
        if url_exists(url, cache, lock):
            return url, tried_urls
    return "", tried_urls


def generate_main_image_urls(image_head: str) -> List[str]:
    candidates = generate_image_candidates(image_head)
    return [f"{BASE_IMAGE_URL}{candidate}" for candidate in candidates]


def generate_sub_image_urls(image_head: str, index: int) -> List[str]:
    if not image_head:
        return []
    sub_head = f"{image_head}_sub{index:02d}"
    candidates = generate_image_candidates(sub_head)
    return [f"{SUB_IMAGE_URL}{candidate}" for candidate in candidates]


def resolve_product_images(
    product: Product, cache: Dict[str, bool], lock: threading.Lock
) -> Tuple[str, List[Dict[str, str]], List[Dict[str, str]]]:
    image_rows: List[Dict[str, str]] = []
    missing_rows: List[Dict[str, str]] = []

    main_urls = generate_main_image_urls(product.image_head)
    main_src, main_tried = find_first_existing(main_urls, cache, lock)
    position = 1

    if main_src:
        image_rows.append(
            {
                "Handle": product.product_id,
                "Image Src": main_src,
                "Image Position": position,
                "Image Alt Text": product.name,
            }
        )
        position += 1
    elif main_urls:
        missing_rows.append(
            {
                "product_id": product.product_id,
                "image_head": product.image_head,
                "kind": "main",
                "tried_urls": "|".join(main_tried),
            }
        )

    for index in range(1, 11):
        sub_urls = generate_sub_image_urls(product.image_head, index)
        if not sub_urls:
            continue
        sub_src, sub_tried = find_first_existing(sub_urls, cache, lock)
        kind = f"sub{index:02d}"
        if sub_src:
            image_rows.append(
                {
                    "Handle": product.product_id,
                    "Image Src": sub_src,
                    "Image Position": position,
                    "Image Alt Text": product.name,
                }
            )
            position += 1
        else:
            missing_rows.append(
                {
                    "product_id": product.product_id,
                    "image_head": product.image_head,
                    "kind": kind,
                    "tried_urls": "|".join(sub_tried),
                }
            )

    return main_src, image_rows, missing_rows


def export_products_sheet(
    products: List[Product],
    category_paths: Dict[str, str],
    output_path: Path,
    missing_output_path: Path,
    images_output_path: Path,
) -> None:
    product_fieldnames = [
        "Handle",
        "Title",
        "Body (HTML)",
        "Vendor",
        "Product Category",
        "Tags",
        "Published",
        "Image Src",
    ]
    missing_fieldnames = ["product_id", "image_head", "kind", "tried_urls"]
    image_fieldnames = ["Handle", "Image Src", "Image Position", "Image Alt Text"]
    url_cache: Dict[str, bool] = {}
    cache_lock = threading.Lock()

    results: List[Optional[Tuple[Dict[str, str], List[Dict[str, str]], List[Dict[str, str]]]]] = [
        None
    ] * len(products)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_index = {
            executor.submit(resolve_product_images, product, url_cache, cache_lock): index
            for index, product in enumerate(products)
        }
        for future in as_completed(future_to_index):
            index = future_to_index[future]
            product = products[index]
            main_src, image_rows, missing_rows = future.result()
            product_row = {
                "Handle": product.product_id,
                "Title": product.name,
                "Body (HTML)": product.body_html,
                "Vendor": "yumejin",
                "Product Category": build_product_category(product, category_paths),
                "Tags": "",
                "Published": "TRUE",
                "Image Src": main_src,
            }
            results[index] = (product_row, image_rows, missing_rows)

    product_rows: List[Dict[str, str]] = []
    image_rows: List[Dict[str, str]] = []
    missing_rows: List[Dict[str, str]] = []

    for result in results:
        if result is None:
            continue
        product_row, product_image_rows, product_missing_rows = result
        product_rows.append(product_row)
        image_rows.extend(product_image_rows)
        missing_rows.extend(product_missing_rows)

    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=product_fieldnames)
        writer.writeheader()
        writer.writerows(product_rows)

    with images_output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=image_fieldnames)
        writer.writeheader()
        writer.writerows(image_rows)

    with missing_output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=missing_fieldnames)
        writer.writeheader()
        if missing_rows:
            writer.writerows(missing_rows)


def export_variants_sheet(products: List[Product], stocks: Dict[str, int], output_path: Path) -> None:
    fieldnames = [
        "Handle",
        "Option1 Name",
        "Option1 Value",
        "SKU",
        "Price",
        "Compare at Price",
        "Inventory Qty",
        "Requires Shipping",
        "Taxable",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for product in products:
            handle = product.product_id
            price, compare_at = select_prices(product)
            writer.writerow(
                {
                    "Handle": handle,
                    "Option1 Name": "Default",
                    "Option1 Value": "Default",
                    "SKU": product.product_id,
                    "Price": price,
                    "Compare at Price": compare_at,
                    "Inventory Qty": stocks.get(product.product_id, 0),
                    "Requires Shipping": "TRUE",
                    "Taxable": "TRUE",
                }
            )


def main() -> None:
    logging.info("商品データ読み込み中: %s", PRODUCT_FILE)
    products = load_products()
    logging.info("カテゴリデータ読み込み中: %s", CATEGORY_FILE)
    categories = load_categories()
    category_paths = build_category_paths(categories)
    logging.info("在庫データ読み込み中: %s", STOCK_FILE)
    stocks = load_stocks()

    OUTPUT_DIR.mkdir(exist_ok=True)
    products_output = OUTPUT_DIR / "yumejin_products_matrixify_products.csv"
    variants_output = OUTPUT_DIR / "yumejin_products_matrixify_variants.csv"
    images_output = OUTPUT_DIR / "yumejin_products_matrixify_images.csv"
    missing_images_output = OUTPUT_DIR / "yumejin_products_matrixify_missing_images.csv"

    logging.info("Products/Images シートを書き出します: %s, %s", products_output, images_output)
    export_products_sheet(
        products, category_paths, products_output, missing_images_output, images_output
    )
    logging.info("Product Variants シートを書き出します: %s", variants_output)
    export_variants_sheet(products, stocks, variants_output)
    logging.info("完了しました")


if __name__ == "__main__":
    main()
