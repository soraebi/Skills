# sprite-gen

**エンジン非依存のゲームキャラ用アニメーションスプライトシート**を生成する [Codex](https://developers.openai.com/codex) スキル。テキストコンセプト・ブランドキュー・参照画像から、Codex 組み込みの画像生成と決定論的な Python パイプライン(フレーム抽出・アトラス合成・検証・視認QA)でスプライトシートを作成します。

[openai/skills](https://github.com/openai/skills) の [`hatch-pet`](https://github.com/openai/skills/tree/main/skills/.curated/hatch-pet) をフォークし、Codex アプリ固定のペット契約(8×9 グリッド・192×208 セル・9状態固定)を完全コンフィグ駆動のスプライトパイプラインへ一般化したものです。

## 特徴

- **コンフィグ駆動のアニメーション仕様**: 状態・フレーム数・フレーム毎の表示時間・アトラスグリッド・セルサイズを解決済みスペック(`sprite_request.json`)で一元管理 — 全スクリプトの単一情報源
- **2つのレンダーモード**: `pixel`(16/32/64px 等の論理ピクセルサイズ。高解像度で生成し、グローバルパレットで決定論的にピクセライズ)と `hires`
- **等身の選択**: `chibi-2` / `toon-3` / `semi-5` / `realistic-7`(頭身比がプロンプトとセル縦横比の既定値に反映)
- **ミラー派生**: `walk-left` を `walk-right` のフレーム単位ミラーとして宣言可能(時間順序を保持・明示承認ゲート付き)— 方向違いの行の画像生成コストを節約
- **エンジン非依存のエクスポート**: `spritesheet.png/webp` + TexturePacker hash 形式の `spritesheet.json`(Phaser / PixiJS でそのまま読込可)+ `animations.json`(状態毎のフレーム・表示時間・ループフラグ・アンカー)+ 任意で状態別ストリップと整数拡大 `@Nx` ペア
- **同梱プリセット**: 6ジャンル × tier(base/plus) × 4等身 = 48種の生成プリセット(`tools/generate_presets.py` による機械生成、詳細は下表)に加え、`minimal`(動作確認用)・`codex-pet`(hatch-pet回帰確認用)

### 内部の仕組み(品質保証)

生成結果の品質を担保するパイプライン内部の機構です。通常の利用で意識する必要はありません。

- **ゲーム向けアンカリング**: bottom-center アンカー+ベースライン安定のフレーム抽出(ゲーム内でのジッタを防止)
- **低姿勢状態のスケール制御**: しゃがみ等で生成モデルがキャラをセルいっぱいに拡大描画してしまう問題への3機構 — `max_height_ratio`(レイアウトガイドに最大身長帯を描画)/ `scale_reference_state`(承認済み行をスケール参照として添付)/ `content_scale`(修復用の決定論的な一様縮小・bottom-center)。詳細は `references/spec-format.md`
- **QAと修復ループ**: コンタクトシート・状態別GIFプレビュー・決定論的検証・最小スコープの行単位修復

## 同梱プリセット一覧

プリセットIDの命名規則は `<family>[-plus]-<proportion>`(例: `topdown-rpg-toon3`, `side-action-plus-real7`)。`base` tier が基礎動作、`-plus` tier が発展動作で、同じ family・同じ等身の base/plus は同一のセル幾何(mode/logical_size/cell)を共有します。48ファイルは手書きではなく `tools/generate_presets.py` が family×tier×等身のテンプレートから機械生成したもので、`--check` で決定論的に再生成し差分ゼロを確認できます。

### 等身(proportion)サフィックスとジオメトリ

| サフィックス | `proportion` 値 | mode | セル/論理サイズ |
|---|---|---|---|
| `chibi2` | `chibi-2` | pixel | 32px(32×32) |
| `toon3` | `toon-3` | pixel | 48px(48×55) |
| `semi5` | `semi-5` | hires | 192×250 |
| `real7` | `realistic-7` | hires | 192×288 |

### ジャンル(family)一覧

imagegen ジョブ数は「非ミラー state 数 + 1(base)」。`prepare_sprite_run.py` が出力する `imagegen job count` は state 総数+1(ミラー行にもジョブエントリを作るため)で、実際に `$imagegen` を呼ぶ必要がある数はこの表の値になります。

| family | ジャンル | view | base states(フレーム数) | base jobs | plus states(フレーム数) | plus jobs |
|---|---|---|---|---|---|---|
| `side-action` | 横スクロールアクション | side | idle(3), run(6), jump-rise(3), fall(3), land(2), attack(5), hurt(3), death(6) | 9 | dash(4), roll(5), wall-slide(2), climb(4), crouch(2), air-attack(4) | 7 |
| `topdown-rpg` | 見下ろしRPG(4方向) | top-down | idle-down(2), walk-down(4), walk-up(4), walk-right(4), walk-left(4, mirror) | 5 | slash-down(4), slash-up(4), slash-right(4), slash-left(4, mirror), cast-down(5), hurt(3), death(6) | 7 |
| `iso-sim` | クォータービューSLG/SRPG | isometric | idle-se(3), walk-se(4), walk-ne(4), walk-sw(4, mirror), walk-nw(4, mirror) | 4 | attack-se(4), attack-sw(4, mirror), guard-se(2), cast-se(5), hurt-se(3), death-se(6) | 6 |
| `beltscroll` | ベルトスクロール格闘 | side | idle(3), walk(4), punch-combo(6), kick(4), hurt(3), knockdown(4), get-up(4), death(6) | 9 | jump(4), air-attack(4), grab(3), throw(4), pickup(3), carry(4) | 7 |
| `adventure` | ポイント&クリック | side | idle(3), walk-right(4), walk-left(4, mirror), walk-down(4), walk-up(4), talk(3) | 6 | pickup(3), use(3), push(3), look(2), sit(2) | 6 |
| `shmup` | シューティング自機 | top-down | idle(2), bank-right(3), bank-left(3, mirror), fire(3), hit(2), explosion(7) | 6 | boost(3), charge(4), barrel-roll(6), transform(5) | 5 |

各 family は上表の base/plus それぞれに 4等身(`chibi2`/`toon3`/`semi5`/`real7`)を掛けた4ファイルがあり、合計 6家族 × 2tier × 4等身 = 48ファイルです。例: `beltscroll` の base は `beltscroll-chibi2` / `beltscroll-toon3` / `beltscroll-semi5` / `beltscroll-real7`。

base/plus を同一キャラで揃えたい場合は、両方の run で同じ `--reference` 画像(`references/canonical-base.png` として保存したもの)を使い回してください。セル幾何が一致しているため、成果物を同じスプライトシートの追加行として結合できます。

### 固定プリセット

| プリセット | 用途 | モード/セル/等身 | 状態(フレーム数) | ジョブ数 |
|---|---|---|---|---|
| `minimal` | 動作確認・使い捨てNPC | pixel 32px / chibi-2 | idle(4), walk-right(6) | 3 |
| `codex-pet` | hatch-pet(Codexアプリ固定ペット契約)との回帰確認専用 | hires 192×208 / chibi-2 | 9状態(hatch-petと同一幾何) | 10 |

## 動作要件

- Codex CLI / Codex アプリ(`$imagegen` システムスキルが利用可能であること)
- Python 3.10+ と [Pillow](https://pypi.org/project/pillow/)(同梱 `scripts/` 用。`uv run --with pillow python ...` などランチャーは任意)
- `jq`(`SKILL.md` に記載のジョブマニフェスト処理で使用)

## インストール

このディレクトリを Codex のスキルフォルダにコピーしてください:

```text
${CODEX_HOME:-$HOME/.codex}/skills/sprite-gen/
```

その後、Codex に次のように依頼します: 「sprite-gen で横スクロール用キャラを作って: 陽気な苔グリーンのスライム騎士、pixel モード、32px、チビ等身」

## ドキュメント

- `SKILL.md` — Codex が従うワークフロー全体(生成委譲・ワーカープロンプト・修復ループ・パッケージング)
- `references/spec-format.md` — スペックのスキーマとプリセット作成ガイド
- `references/output-formats.md` — エクスポートファイル形式と Phaser/PixiJS の読込スニペット
- `references/qa-rubric.md` — 視認QAのルーブリック

## ライセンス

Apache License 2.0(`LICENSE.txt` 参照)。本スキルは [openai/skills](https://github.com/openai/skills) の `hatch-pet` を改変したフォークです。主な変更点: コンフィグ駆動のスペックシステム(`scripts/spec_lib.py`)、ピクセルアートパイプライン(`scripts/pixelize_frames.py`)、エンジン非依存エクスポータ(`scripts/export_spritesheet.py`)、ミラー派生の一般化、スキル/リファレンスドキュメントの全面書き直し。
