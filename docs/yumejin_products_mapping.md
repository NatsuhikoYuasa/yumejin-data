# yumejin 商品データ CSV 解析と Shopify 取り込み設計（フェーズ1）

## 1. CSV ファイル一覧と想定役割

| ファイル名 | 行数 (ヘッダー含む) | 想定役割 | 備考 |
| --- | --- | --- | --- |
| `Product20251211.csv` | 4,874 行 | 商品マスタ。商品 ID、商品名、説明文、価格表示、カテゴリ、関連商品、画像ヘッダーなどを保持。 | 111 カラム。文字コードは Shift_JIS。`product_id` をキーに他ファイルへ連携。 |
| `ProductVariation20251211.csv` | 0 行 | バリアント詳細（推測）。 | データ未投入。今後、容量違いなどバリアントがある場合に利用予定。 |
| `ProductPrice20251211.csv` | 0 行 | 価格マスタ（推測）。 | データ未投入。定価・特価や会員価格を商品/バリアント単位で持つ想定。 |
| `ProductStock20251211.csv` | 2 行 | 在庫マスタ。`product_id` と `variation_id` 別の在庫数量を保持。 | 現状 1 商品分のサンプルのみ。 |
| `ProductCategory20251211.csv` | 22 行 | カテゴリマスタ。階層構造を持ち、`category_id` と `parent_category_id` を保持。 | `name`/`name_kana` などカテゴリ表示名を含む。 |
| `ProductTag20251211.csv` | 349 行 | 商品タグの紐づけ。`product_id` ごとのタグ行。 | タグ名称は欠落しており、タグ付与の履歴のみ（推測）。 |
| `ProductReview20251211.csv` | 0 行 | レビュー情報（推測）。 | データ未投入。 |

> 備考: 行数は `wc -l` による集計。空ファイルはヘッダーも未定義。

## 2. 主なカラムと意味（推測を含む）

### Product20251211.csv（商品マスタ）
- `product_id`: 内部商品コード。タグ・在庫・関連商品参照のキー。
- `name` / `name_kana`: 商品名と読み（推測）。
- `seo_keywords`: SEO 用キーワード（推測）。
- `catchcopy` / `catchcopy_mobile`: 商品のキャッチコピー（PC/モバイル別）。
- `outline_kbn`, `outline`: 商品概要の種別と本文（推測）。
- `desc_detail_kbn1-4`, `desc_detail1-4`: 詳細説明の種別/本文（4 枠まで）。`*_mobile` 列はモバイル表示用。
- `return_exchange_message`: 返品・交換に関する注記（推測）。
- `display_price` / `display_special_price`: 表示価格とセール価格（推測）。
- `shipping_type`, `shipping_size_kbn`: 配送方法/サイズ区分。
- `point_kbn1`, `point1`: ポイント付与区分と数値（推測）。
- `display_from` / `display_to`, `sell_from` / `sell_to`: 掲載・販売の開始/終了日時。
- `max_sell_quantity`: 1 受注あたりの上限数（推測）。
- `stock_management_kbn`, `stock_message_id`: 在庫管理種別と在庫表示メッセージ（推測）。
- `url`: 商品詳細ページのパス。
- `inquire_email`, `inquire_tel`: 問い合わせ先。
- `display_kbn`: 表示/非表示区分。
- `category_id1-5`: 商品に紐づく最大 5 つのカテゴリ ID。
- `related_product_id_cs1-5` / `related_product_id_us1-5`: 関連商品 ID（クロスセル/アップセルの別枠と推測）。
- `image_head`, `image_mobile`: 代表画像のキー/パス（推測）。
- `icon_flg1-10`, `icon_term_end1-10`: アイコン表示フラグと終了日。10 種類まで設定可能。
- `mobile_disp_flg`: モバイル表示フラグ。
- `use_variation_flg`: バリアント利用有無。
- `fixed_purchase_flg`: 定期購入フラグ。
- `member_rank_discount_flg`, `display_member_rank`, `buyable_member_rank`: 会員ランク別の表示/購入制御（推測）。
- `valid_flg`: 有効/無効。
- `google_shopping_flg`: Google Shopping 連携可否（推測）。
- `product_option_settings`: オプション設定（JSON などの文字列が入る想定）。
- `arrival_mail_valid_flg`, `release_mail_valid_flg`, `resale_mail_valid_flg`: 入荷/発売/再販通知メール設定。
- `select_variation_kbn`, `select_variation_kbn_mobile`: バリアント選択 UI 種別（PC/モバイル）。
- `plural_shipping_price_free_flg`: 複数配送でも送料無料か。
- `age_limit_flg`: 年齢制限。
- `digital_contents_flg`, `download_url`: デジタル商品のフラグと URL。
- `display_sell_flg`: 販売可否。
- `display_priority`: 並び順（推測）。

### ProductStock20251211.csv（在庫）
- `product_id`, `variation_id`: 商品/バリアントのキー。バリアントが無い場合は同一値。
- `stock`, `stock_alert`: 在庫数とアラート閾値（推測）。
- `realstock`, `realstock_b`, `realstock_c`, `realstock_reserved`: 実在庫や予約在庫など複数の在庫バッファ（推測）。
- `date_created`, `date_changed`, `last_changed`: 更新日時。

### ProductCategory20251211.csv（カテゴリ）
- `category_id`: カテゴリ固有 ID。
- `parent_category_id`: 親カテゴリ ID。`root` で最上位。
- `name` / `name_kana`: カテゴリ名と読み。
- `name_mobile`: モバイル用表示名。
- `seo_keywords`: カテゴリの SEO キーワード（推測）。
- `url`: カテゴリページのパス（推測）。
- `mobile_disp_flg`, `valid_flg`: 表示/有効フラグ。
- `member_rank_id`, `lower_member_can_display_tree_flg`: 会員権限による閲覧制御（推測）。
- `display_order`: 並び順。
- `child_category_sort_kbn`: 子カテゴリのソート種別（推測）。

### ProductTag20251211.csv（タグ紐づけ）
- `product_id`: タグ付与対象の商品 ID。
- `date_created`, `date_changed`, `last_changed`: 付与日時。タグ名自体は別マスタにある想定（未提供）。

### 空ファイル（Price / Variation / Review）
- カラム定義が無いため、今後必要な場合は Shopify 用カラムへ読み替える設計が必要。

## 3. CSV 同士の関係性
- 主キー: `product_id` が商品全体のキー。`ProductTag`、`ProductStock`、`ProductVariation`（データなしだが設計上）、`ProductPrice`（同左）が参照。
- バリアント: `use_variation_flg` が 1 の商品で、`ProductVariation`（未提供）や `variation_id` 列を通じて SKU 単位に分岐する想定。現状は商品とバリアント ID が同じ値の在庫行のみ確認。
- 画像: `image_head`/`image_mobile` などが画像ファイル名/キー。複数画像マスタは未提供のため、商品マスタ側のキーを Shopify の画像パスに変換する前提で設計。
- カテゴリ: `ProductCategory` の `category_id` を `Product` の `category_id1-5` が参照。`parent_category_id` により階層構造を持つ。
- タグ: `ProductTag` は `product_id` のみを保持し、タグ名は別途管理（推測）。Shopify ではタグ文字列を生成する追加ロジックが必要。
- 関連商品: `related_product_id_cs1-5` / `related_product_id_us1-5` で商品間リンク。Shopify ではメタフィールドやレコメンドアプリで再現。

## 4. Shopify へのマッピング案

### Shopify 標準項目への対応表

| 元 CSV | 主キー | Shopify | 内容 | 備考 |
| --- | --- | --- | --- | --- |
| Product | `product_id` | Product: Handle | `product_id` をそのまま Handle として使用。 | ハンドルは一意制約。 |
| Product | `name` | Product: Title | 商品名。 | 日本語タイトル可。 |
| Product | `catchcopy`/`outline`/`desc_detail*` | Product: Body (HTML) | 説明文を結合し HTML 化。 | モバイル別文面は注釈として統合。 |
| Product | `display_price` / `display_special_price` | Variant: Price / Compare at Price | セール価格があれば `price` と `compare_at_price` を使い分け。 | バリアントが無い場合は単一バリアント。 |
| Product | `use_variation_flg` + ProductVariation (将来) | Variant: Options/Values | 容量/カラーなどを Options に展開。 | Variation CSV がないため設計のみ。 |
| ProductStock | `variation_id` | Variant: Inventory Quantity | 在庫数をインポート。 | `inventory_policy` は在庫管理区分に応じ決定。 |
| Product | `shipping_type` / `shipping_size_kbn` | Variant: Weight / Requires Shipping | 配送サイズから重量換算（ルール設計が必要）。 | 情報不足時は固定値。 |
| Product | `category_id1-5` | Collection | ルートから子へ辿って自動コレクション/手動コレクションを作成。 | 階層はメタフィールドで保持も可。 |
| Product | `image_head` / `image_mobile` | Product Image | 画像パスを URL 化し添付。 | 追加画像が必要なら別マスタを拡張。 |
| ProductTag | `product_id` | Product: Tags | タグ文字列を生成して付与（例: 外部タグマスタから）。 | 現 CSV だけではタグ名が欠落。 |
| Product | `related_product_id_*` | Metafield (product_reference) | 関連商品リンクをメタフィールドに保持。 | Matrixify の Metafields シートで対応。 |
| Product | `fixed_purchase_flg` | Metafield (boolean) | 定期購入可否。 | サブスクアプリ連携を想定。 |
| Product | `google_shopping_flg` | Metafield (boolean) | Google Shopping 連携可否。 | 別チャンネル制御用。 |
| Product | `display_priority` | Metafield (integer) | 並び順のカスタムメタ。 | コレクション並び替えで活用。 |

### メタフィールド候補（例）
- `custom.skin_type` (list.single_line_text_field): 敏感肌 / 乾燥肌 など。
- `custom.usage_area` (list.single_line_text_field): フェイス / ボディ / ヘア。
- `custom.key_ingredients` (list.multi_line_text_field or list.rich_text): 主要成分。
- `custom.origin_area` (single_line_text_field): 産地（例: 沖縄・石垣島）。
- `custom.how_to_use` (rich_text): 使用方法。
- `custom.capacity` (single_line_text_field): 容量表記（例: "150ml"）。
- `custom.texture` (single_line_text_field): テクスチャ（ジェル/クリームなど）。
- `custom.fragrance` (single_line_text_field): 香り。
- `custom.subscription_flag` (boolean): `fixed_purchase_flg` の移送先。
- `custom.google_shopping` (boolean): `google_shopping_flg` の移送先。
- `custom.related_cs` / `custom.related_us` (product_reference): 関連商品リンク。

### メタオブジェクト候補
- ブランドマスタ（例: `brand`）: yumejin 固有情報、ロゴ、ブランドストーリー。
- ライン/シリーズ（例: `line`）: カテゴリの特定階層をメタオブジェクト化して詳細説明やバナーを保持。
- 成分マスタ（例: `ingredient`）: 成分名、由来、画像、説明を格納し、商品メタフィールドで参照。
- 産地マスタ（例: `origin`）: 産地名、地図、ストーリーを格納。

## 5. Matrixify インポート用シート設計

### Products シート
- 必須カラム例: `Handle`, `Title`, `Body (HTML)`, `Vendor`, `Product Category`, `Tags`, `Published`, `Image Src`。
- 変換ルール:
  - `Handle`: `product_id` をそのまま使用（Shopify 上で一意になる前提）。
  - `Title`: `name`。
  - `Body (HTML)`: `catchcopy`/`outline`/`desc_detail*` を HTML で連結。
  - `Product Category`: `category_id1-5` を `/` 区切りで階層名に変換（`ProductCategory` を JOIN）。
  - `Tags`: `ProductTag` からタグ文字列を生成。タグ名不足の場合は `product_id` ベースの暫定タグも可。
  - `Image Src`: `image_head` をベース URL と連結。追加画像は将来別 CSV で拡張。

### Product Variants シート
- カラム例: `Handle`, `Option1 Name/Value`, `SKU`, `Price`, `Compare at Price`, `Inventory Qty`, `Barcode`, `Weight`, `Requires Shipping`, `Taxable`。
- 変換ルール:
  - バリアント未提供の場合はデフォルト 1 行。`SKU` に `product_id` を利用。
  - `Price`/`Compare at Price`: `display_price`/`display_special_price` から算出。
  - `Inventory Qty`: `ProductStock` を `product_id` + `variation_id` で JOIN。
  - オプション名は「容量」「色」などバリアント軸に応じて設定（設計フェーズ）。

### Metafields シート
- カラム例: `Owner Type`, `Owner Identifier`, `Namespace`, `Key`, `Type`, `Value`。
- 主な投入候補: `subscription_flag`, `google_shopping`, `related_cs/us`, `display_priority`, `skin_type`, `usage_area`, `key_ingredients`, `origin_area`, `how_to_use`, `capacity`, `texture`, `fragrance`。
- `Owner Type` は `product`。`Owner Identifier` に `Handle` を使用。

### Metaobjects シート（必要に応じて）
- カラム例: `Type`, `Handle`, `Field: name`, `Field: description`, `Field: image`, ...
- `brand`, `line`, `ingredient`, `origin` などの型を定義し、Products/Metafields シートから参照（`metaobject_reference`）で接続。

### Collections シート
- カラム例: `Title`, `Handle`, `Body (HTML)`, `Published`, `Rule: Column`, `Rule: Relation`, `Rule: Condition`。
- `ProductCategory` をもとに階層コレクションを作成。`category_id` と `parent_category_id` を用いてハンドルを生成。

## 6. 今後の変換ロジックのメモ（フェーズ2準備）
- 文字コード: すべて Shift_JIS で読み込み UTF-8 へ変換する。
- 空ファイル（Price/Variation/Review）は仕様を決めてダミーカラムを生成するか、別ソースから取得する。
- タグ名は別マスタが必要。無い場合はカテゴリ名やプロパティから自動生成する。
- 画像パスは共通ベース URL を設定し、`image_head`/`image_mobile` をファイル名として結合する。

## 実行手順（Products/Variants シート生成）
1. ルートディレクトリで Python を実行します。
   ```bash
   python scripts/generate_matrixify_products.py
   ```
2. `output/` 配下に Matrixify 用の CSV が生成されます。
   - `output/yumejin_products_matrixify_products.csv`（Products シート）
   - `output/yumejin_products_matrixify_variants.csv`（Product Variants シート）
3. 生成したファイルを Matrixify の対応シートとしてアップロードしてください。

