"""
Matrixify 向けに yumejin の商品データを変換するスクリプト。

- products/ 配下の Shift_JIS CSV を読み込み、UTF-8 で Matrixify が受け取れる形式の CSV を生成する。
- 現状はバリアント 1 つの商品だけを想定し、価格・カテゴリ・画像の最低限の情報を出力する。
"""
from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, List, Optional, Sequence

# 将来本番環境の URL に差し替えることを想定したベース URL
BASE_IMAGE_URL = "https://www.example.com/images/products/"

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


def build_image_src(product: Product) -> str:
    if not product.image_head:
        return ""
    return f"{BASE_IMAGE_URL}{product.image_head}.jpg"


def export_products_sheet(products: List[Product], category_paths: Dict[str, str], output_path: Path) -> None:
    fieldnames = [
        "Handle",
        "Title",
        "Body (HTML)",
        "Vendor",
        "Product Category",
        "Tags",
        "Published",
        "Image Src",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for product in products:
            handle = product.product_id
            writer.writerow(
                {
                    "Handle": handle,
                    "Title": product.name,
                    "Body (HTML)": product.body_html,
                    "Vendor": "yumejin",
                    "Product Category": build_product_category(product, category_paths),
                    "Tags": "",
                    "Published": "TRUE",
                    "Image Src": build_image_src(product),
                }
            )


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

    logging.info("Products シートを書き出します: %s", products_output)
    export_products_sheet(products, category_paths, products_output)
    logging.info("Product Variants シートを書き出します: %s", variants_output)
    export_variants_sheet(products, stocks, variants_output)
    logging.info("完了しました")


if __name__ == "__main__":
    main()
